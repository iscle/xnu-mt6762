#!/usr/bin/env python3
"""Boot only the delivered Android image's Image and a synthetic LK FDT.

This is an emulator diagnostic, never a physical-device readiness test.
No external XNU segments, Apple tree, boot_args, or userland are loaded.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

import bootimg
import trace_record
import display_record
import pwm_record
import peripheral_record


def digest(data):
    return hashlib.sha256(data).hexdigest()


def runtime_fdt(original, ram_bytes):
    """Change only the existing memory/reg value; preserve reservations exactly."""
    data = bytearray(original)
    magic, total, start, strings, *_ = struct.unpack_from('>10I', data)
    if magic != 0xd00dfeed or total != len(data):
        raise ValueError('invalid FDT')
    offset, nodes, matches = start, [], []
    while offset < len(data):
        token, = struct.unpack_from('>I', data, offset)
        offset += 4
        if token == 1:
            end = data.index(0, offset)
            nodes.append(bytes(data[offset:end]).decode())
            offset = (end + 4) & ~3
        elif token == 2:
            nodes.pop()
        elif token == 3:
            size, nameoff = struct.unpack_from('>II', data, offset)
            offset += 8
            end = data.index(0, strings + nameoff)
            name = bytes(data[strings + nameoff:end]).decode()
            if len(nodes) == 2 and nodes[-1].split('@')[0] == 'memory' and name == 'reg':
                if size != 16 or struct.unpack_from('>Q', data, offset)[0] != 0x40000000:
                    raise ValueError('unexpected stock memory encoding')
                matches.append(offset)
            offset = (offset + size + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            break
        else:
            raise ValueError('invalid FDT token')
    if len(matches) != 1:
        raise ValueError('expected one stock memory/reg')
    struct.pack_into('>Q', data, matches[0] + 8, ram_bytes)
    return bytes(data), matches[0] + 8


def display_fdt(original):
    """Add an explicitly synthetic LK framebuffer tag and exact reservation."""
    h = list(struct.unpack_from('>10I', original))
    structure = original[h[2]:h[2] + h[9]]
    strings = original[h[3]:h[3] + h[8]]
    offset, depth, insertion = 0, 0, None
    while offset < len(structure):
        token, = struct.unpack_from('>I', structure, offset); offset += 4
        if token == 1:
            end = structure.index(0, offset)
            name = structure[offset:end]
            offset = (end + 4) & ~3
            depth += 1
            if depth == 2 and name == b'chosen':
                if insertion is not None:
                    raise ValueError('duplicate chosen node')
                insertion = offset
        elif token == 2:
            depth -= 1
        elif token == 3:
            length, nameoff = struct.unpack_from('>II', structure, offset)
            name = strings[nameoff:strings.index(0, nameoff)]
            if name == b'atag,videolfb' or name.startswith(b'videolfb-'):
                raise ValueError('refusing to replace existing framebuffer provenance')
            offset = (offset + 8 + length + 3) & ~3
        elif token == 9:
            break
        elif token != 4:
            raise ValueError('invalid FDT structure')
    if insertion is None:
        raise ValueError('no chosen node in stock FDT')
    value = struct.pack('<QIII', 0x7ef90000, 1, 6000, 0x470000) + b'QEMU-SYNTHETIC\0'
    value += bytes(-len(value) % 4)  # LK tag structure includes padded panel name.
    prop = struct.pack('>III', 3, len(value), len(strings)) + value
    prop += bytes(-len(prop) % 4)
    structure = structure[:insertion] + prop + structure[insertion:]
    strings += b'atag,videolfb\0'
    reserve_end = h[4]
    while struct.unpack_from('>QQ', original, reserve_end) != (0, 0):
        reserve_end += 16
    reservations = original[h[4]:reserve_end] + struct.pack('>QQ', 0x7ef90000, 0x470000) + bytes(16)
    h[4] = 40; h[2] = 40 + len(reservations); h[3] = h[2] + len(structure)
    h[8] = len(strings); h[9] = len(structure); h[1] = h[3] + len(strings)
    return struct.pack('>10I', *h) + reservations + structure + strings


class QMP:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.settimeout(5)
        self.sock.connect(str(path)); self.stream = self.sock.makefile('rwb')
        json.loads(self.stream.readline())
        self.command('qmp_capabilities')

    def command(self, command, arguments=None):
        self.stream.write(json.dumps(dict(execute=command, arguments=arguments or {})).encode() + b'\n')
        self.stream.flush()
        while True:
            reply = json.loads(self.stream.readline())
            if 'error' in reply:
                raise RuntimeError(reply)
            if 'return' in reply:
                return reply['return']


class RSP:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(5)
        self.sock.connect(str(path))

    def packet(self, command, response=True):
        data = command.encode()
        self.sock.sendall(b'$' + data + b'#' + f'{sum(data) & 255:02x}'.encode())
        if not response:
            return None
        return self.receive()

    def receive(self):
        while True:
            byte = self.sock.recv(1)
            if not byte:
                raise RuntimeError('GDB disconnected before packet')
            if byte == b'$':
                break
        raw = bytearray()
        while True:
            byte = self.sock.recv(1)
            if not byte:
                raise RuntimeError('GDB disconnected')
            if byte == b'#':
                break
            raw += byte
        checksum = b''
        while len(checksum) < 2:
            part = self.sock.recv(2 - len(checksum))
            if not part:
                raise RuntimeError('truncated GDB checksum')
            checksum += part
        if int(checksum, 16) != sum(raw) & 255:
            raise RuntimeError('GDB checksum mismatch')
        self.sock.sendall(b'+')
        decoded = bytearray()
        i = 0
        while i < len(raw):
            if raw[i] == 125:
                i += 1
                decoded.append(raw[i] ^ 32)
            else:
                decoded.append(raw[i])
            i += 1
        return decoded.decode()

    def xml(self, name):
        output = ''
        while True:
            reply = self.packet(f'qXfer:features:read:{name}:{len(output):x},800')
            if not reply or reply[0] not in 'ml':
                raise RuntimeError(f'GDB XML unavailable: {name}: {reply}')
            output += reply[1:]
            if reply[0] == 'l':
                return output

    def registers(self, output):
        result, nextnum = {}, 0

        def visit(name):
            nonlocal nextnum
            content = self.xml(name)
            (output / name).write_text(content)
            # QEMU's target.xml uses xi:include without declaring xmlns:xi.
            root = ET.fromstring(content.replace('xi:include', 'include'))
            for elem in root.iter():
                if elem.tag.endswith('include'):
                    visit(elem.attrib['href'])
                elif elem.tag == 'reg':
                    number = int(elem.get('regnum', str(nextnum)), 0)
                    result[elem.attrib['name']] = (number, int(elem.attrib['bitsize']))
                    nextnum = number + 1
        visit('target.xml')
        return result

    def read(self, reg):
        raw = self.packet(f'p{reg[0]:x}')
        if len(raw) != reg[1] // 4:
            raise RuntimeError(f'bad register read: {reg}: {raw}')
        return int.from_bytes(bytes.fromhex(raw), 'little')

    def write(self, reg, value):
        reply = self.packet(f'P{reg[0]:x}={value.to_bytes(reg[1] // 8, "little").hex()}')
        if reply != 'OK' or self.read(reg) != value:
            raise RuntimeError(f'register write failed: {reg}: {reply}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--static-memory', action='store_true')
    parser.add_argument('--memory-mib',type=int,default=4096,choices=(4096,6144))
    parser.add_argument('--runtime-fdt',type=Path,help='replay an exact captured LK FDT; never proof of physical execution')
    parser.add_argument('--display-fixture', action='store_true')
    parser.add_argument('--two-layer-display', action='store_true',
                        help='explicit QEMU LK menu-layer fixture; requires --display-fixture')
    parser.add_argument('--visible-console', action='store_true',
                        help='capture video-console diagnostic; requires separate visual result review')
    parser.add_argument('--native-display', action='store_true', help='expect native display/PWM consumer admission')
    parser.add_argument('--brightness-pulse', action='store_true', help='expect two bounded PWM commits and restoration')
    parser.add_argument('--expect-native-refusal', action='store_true')
    parser.add_argument('--log-address', type=lambda value:int(value,0))
    parser.add_argument('--log-length-address', type=lambda value:int(value,0))
    parser.add_argument('--seconds', type=float, default=40)
    parser.add_argument('--exception-at', type=lambda value:int(value, 0),
                        help='QEMU-only hardware breakpoint at loader_main, then execute owned zero padding to test fatal trace')
    args = parser.parse_args()
    if args.two_layer_display and not args.display_fixture:
        parser.error('--two-layer-display requires --display-fixture')
    if args.visible_console and (not args.display_fixture or args.static_memory):
        parser.error('--visible-console requires positive --display-fixture')
    if bool(args.log_address) != bool(args.log_length_address):
        parser.error('both log addresses are required')
    if args.native_display and (not args.two_layer_display or not args.log_address):
        parser.error('native display validation requires two-layer fixture and kernel log addresses')
    if args.brightness_pulse and not args.native_display:
        parser.error('brightness pulse validation requires native display')
    args.output.mkdir(parents=True, exist_ok=False)
    image = bootimg.parse(args.image.read_bytes())
    bootimg.kernel_gzip_info(image.parts['kernel'])
    raw = gzip.decompress(image.parts['kernel'])
    if args.exception_at is not None:
        if args.static_memory or args.display_fixture or not 0x40084100 <= args.exception_at < 0x40200000:
            parser.error('exception test requires a bounded loader_main address and no other fixtures')
        if raw[0x3ffc:0x4000] != bytes(4):
            raise ValueError('Expected undefined instruction in owned pre-trace padding')
    entries = bootimg.dt_table(image.parts['dtb'])['entries']
    if len(entries) != 1 or image.address('kernel') != 0x40080000 or image.address('dtb') != 0x47880000:
        raise ValueError('unsupported physical image addresses/DT selection')
    ent = entries[0]
    stock = image.parts['dtb'][ent['offset']:ent['offset'] + ent['size']]
    if args.runtime_fdt:
        if args.static_memory:parser.error('captured FDT and static memory are mutually exclusive')
        fdt=args.runtime_fdt.read_bytes();patch=None
        matched,_=runtime_fdt(fdt,args.memory_mib*1024**2)
        if matched!=fdt:raise ValueError('captured FDT RAM size does not match QEMU')
    else:
        fdt, patch = (stock, None) if args.static_memory else runtime_fdt(stock,args.memory_mib*1024**2)
    if args.display_fixture and not args.runtime_fdt:
        fdt = display_fdt(fdt)
    rawpath, fdtpath = args.output / 'Image', args.output / 'runtime.dtb'
    rawpath.write_bytes(raw)
    fdtpath.write_bytes(fdt)
    report = dict(kind='synthetic-LK-QEMU-only', physical_validation=False,
                  delivered_image_sha256=image.source_sha256, image_sha256=digest(raw),
                  stock_dtb_sha256=digest(stock), runtime_dtb_sha256=digest(fdt),
                  changed_memory_size_offset=patch, static_memory=args.static_memory,
                  synthetic_display=args.display_fixture,
                  synthetic_two_layer_display=args.two_layer_display,
                  manual_visible_console_review_required=args.visible_console,
                  external_payloads=['image-derived Image', 'image-derived runtime FDT'])
    trace_bytes = raw[trace_record.OFFSET:trace_record.OFFSET + trace_record.SIZE]
    traced = trace_bytes[:8] == trace_record.MAGIC
    if traced:
        identity = trace_bytes[16:48]
        report['trace_file'] = trace_record.decode(trace_bytes, identity)
    display_bytes = raw[display_record.OFFSET:display_record.OFFSET + display_record.SIZE]
    display_traced = traced and display_bytes[:8] == display_record.MAGIC
    if display_traced:
        report['display_file'] = display_record.decode(display_bytes, identity)
    pwm_bytes = raw[pwm_record.OFFSET:pwm_record.OFFSET + pwm_record.SIZE]
    pwm_traced = traced and pwm_bytes[:8] == pwm_record.MAGIC
    if pwm_traced:
        report['pwm_file'] = pwm_record.decode(pwm_bytes, identity)
    peripheral_bytes=raw[peripheral_record.OFFSET:peripheral_record.OFFSET+peripheral_record.SIZE]
    peripheral_traced=traced and peripheral_bytes[:8]==peripheral_record.MAGIC
    if peripheral_traced:report['peripheral_file']=peripheral_record.decode(peripheral_bytes,identity)
    with tempfile.TemporaryDirectory(prefix='mtk-physical-') as tmp:
        gdb = Path(tmp) / 'gdb'
        qmp_path = Path(tmp) / 'qmp'
        machine = 'mt6762' + (',lab-i2c=on,lab-display=on,lab-display-fb=0x7ef90000' if args.display_fixture else '')
        if args.two_layer_display:
            machine += ',lab-display-two-layer=on'
        cmd = [str(args.qemu.resolve()), '-M', machine, '-cpu', 'cortex-a53', '-smp', '1',
               '-m', f'{args.memory_mib}M', '-dtb', str(fdtpath.resolve()), '-display', 'none',
               '-serial', 'file:' + str((args.output / 'serial.log').resolve()), '-monitor', 'none',
               '-S', '-gdb', f'unix:{gdb},server=on,wait=off',
               '-qmp', f'unix:{qmp_path},server=on,wait=off',
               '-device', f'loader,file={rawpath.resolve()},addr=0x40080000,force-raw=on',
               '-device', f'loader,file={fdtpath.resolve()},addr=0x47880000,force-raw=on']
        report['command'] = cmd
        with (args.output / 'qemu.log').open('wb') as err:
            proc = subprocess.Popen(cmd, stdout=err, stderr=err)
            try:
                deadline = time.monotonic() + 10
                while not gdb.exists():
                    if proc.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('QEMU GDB startup failed')
                    time.sleep(.02)
                rsp = RSP(gdb)
                qmp = QMP(qmp_path)
                if traced:
                    before = args.output / 'trace-before.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {trace_record.ADDRESS:#x} {trace_record.SIZE:#x} "{before.resolve()}"'})
                    report['trace_before'] = trace_record.decode(before.read_bytes(), identity)
                    if before.read_bytes() != trace_bytes:
                        raise RuntimeError('QEMU physical trace differs from loaded initialized Image')
                if display_traced:
                    before = args.output / 'display-before.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {display_record.ADDRESS:#x} {display_record.SIZE:#x} "{before.resolve()}"'})
                    if before.read_bytes() != display_bytes:
                        raise RuntimeError('QEMU display record differs from loaded Image')
                if pwm_traced:
                    before = args.output / 'pwm-before.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {pwm_record.ADDRESS:#x} {pwm_record.SIZE:#x} "{before.resolve()}"'})
                    if before.read_bytes() != pwm_bytes:
                        raise RuntimeError('QEMU PWM record differs from loaded Image')
                report['gdb_capabilities'] = rsp.packet('qSupported:multiprocess+;qXfer:features:read+')
                regs = rsp.registers(args.output)
                report['registers'] = regs
                report['initial_registers'] = {name:rsp.read(regs[name]) for name in
                    ['pc', 'cpsr', 'x0', 'SCTLR_EL1', 'CNTFRQ_EL0']}
                if (report['initial_registers']['cpsr'] >> 2) & 3 not in (1, 2):
                    raise RuntimeError('unexpected initial EL')
                for name, value in [('pc', 0x40080000), ('x0', 0x47880000), ('x1', 0), ('x2', 0), ('x3', 0)]:
                    rsp.write(regs[name], value)
                if args.exception_at is not None:
                    if not traced or rsp.packet(f'Z1,{args.exception_at:x},4') != 'OK':
                        raise RuntimeError('Cannot install explicit QEMU exception-test breakpoint')
                    rsp.packet('c', response=False)
                    report['exception_break_reply'] = rsp.receive()
                    if rsp.read(regs['pc']) != args.exception_at:
                        raise RuntimeError('Exception-test breakpoint not reached')
                    if rsp.packet(f'z1,{args.exception_at:x},4') != 'OK':
                        raise RuntimeError('Cannot remove exception-test breakpoint')
                    rsp.write(regs['pc'], 0x40083ffc)
                    report['exception_injection'] = dict(pc=0x40083ffc,
                        method='QEMU register-only diversion into owned Image zero padding')
                rsp.packet('c', response=False)
                deadline = time.monotonic() + args.seconds
                while time.monotonic() < deadline and proc.poll() is None:
                    text = (args.output / 'serial.log').read_text(errors='replace')
                    if 'MT6762_IIG_PROBE_DONE' in text or 'Watchdog policy unchanged; no XNU entry.' in text or (args.exception_at is not None and '!1:' in text):
                        break
                    time.sleep(.1)
                rsp.sock.sendall(b'\x03')
                report['stop_reply'] = rsp.receive()
                report['final_registers'] = {name:rsp.read(regs[name]) for name in
                    ['pc', 'cpsr', 'x0', 'x1', 'x2', 'x19', 'x20', 'sp',
                     'ESR_EL1', 'ELR_EL1', 'FAR_EL1', 'SCTLR_EL1', 'TCR_EL1', 'CNTFRQ_EL0']}
                rsp.sock.close()
                if traced:
                    after = args.output / 'trace-after.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {trace_record.ADDRESS:#x} {trace_record.SIZE:#x} "{after.resolve()}"'})
                    report['trace_after'] = trace_record.decode(after.read_bytes(), identity)
                    report['trace_after_sha256'] = digest(after.read_bytes())
                if display_traced:
                    after = args.output / 'display-after.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {display_record.ADDRESS:#x} {display_record.SIZE:#x} "{after.resolve()}"'})
                    report['display_after'] = display_record.decode(after.read_bytes(), identity)
                    report['display_after_sha256'] = digest(after.read_bytes())
                if pwm_traced:
                    after = args.output / 'pwm-after.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {pwm_record.ADDRESS:#x} {pwm_record.SIZE:#x} "{after.resolve()}"'})
                    report['pwm_after'] = pwm_record.decode(after.read_bytes(), identity)
                    report['pwm_after_sha256'] = digest(after.read_bytes())
                if args.log_address and report.get('trace_after',{}).get('phase') == 10:
                    ram = report['trace_after']['ram']
                    if not (ram <= args.log_address <= ram + 0x20000000 - 0x180000 and
                            ram <= args.log_length_address <= ram + 0x20000000 - 4):
                        raise ValueError('log addresses outside admitted XNU RAM window')
                    length_path=args.output/'kernel-log-length.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {args.log_length_address:#x} 4 "{length_path.resolve()}"'})
                    length,=struct.unpack('<I',length_path.read_bytes())
                    if not 0 < length <= 0x180000:
                        raise ValueError('kernel log length outside allocation')
                    log_path=args.output/'kernel-log.bin'
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {args.log_address:#x} {length:#x} "{log_path.resolve()}"'})
                    report['kernel_log']=dict(address=args.log_address,length_address=args.log_length_address,
                        bytes=length,sha256=digest(log_path.read_bytes()))
                if report.get('trace_after',{}).get('phase')==10:
                    args_pa=report['trace_after']['args'];ram=report['trace_after']['ram']
                    if not ram<=args_pa<ram+0x20000000-736:raise ValueError('boot args outside initial owned window')
                    path=args.output/'runtime-boot-args.bin'
                    qmp.command('pmemsave',{'val':args_pa,'size':736,'filename':str(path.resolve())})
                    ba=path.read_bytes()
                    base,size=struct.unpack_from('<2Q',ba,16)
                    actual,=struct.unpack_from('<Q',ba,728)
                    report['runtime_memory']=dict(physical_base=base,usable_bytes=size,actual_bytes=actual)
                if peripheral_traced:
                    path=args.output/'peripheral-after.bin'
                    qmp.command('pmemsave',{'val':peripheral_record.ADDRESS,'size':peripheral_record.SIZE,'filename':str(path.resolve())})
                    report['peripheral_after']=peripheral_record.decode(path.read_bytes(),identity)
                if args.display_fixture:
                    report['display_state'] = json.loads(qmp.command('qom-get',
                        {'path':'/machine', 'property':'lab-display-state'}))
                    framebuffer = args.output / 'framebuffer.bgra'
                    framebuffer_base = 0x7f0d4000 if args.two_layer_display else 0x7ef90000
                    qmp.command('human-monitor-command', {'command-line':
                        f'pmemsave {framebuffer_base:#x} 0x144000 "{framebuffer.resolve()}"'})
                    pixels = framebuffer.read_bytes()
                    report['framebuffer_sha256'] = digest(pixels)
                    report['framebuffer_nonzero_bytes'] = sum(byte != 0 for byte in pixels)
                    report['framebuffer_base'] = framebuffer_base
                    report['framebuffer_alpha_opaque'] = all(v == 255 for v in pixels[3:384*854*4:4])
                    from PIL import Image
                    Image.frombytes('RGBA', (384, 854), pixels[:384*854*4], 'raw', 'BGRA').convert('RGB').save(args.output / 'framebuffer.png')
                qmp.stream.close(); qmp.sock.close()
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    text = (args.output / 'serial.log').read_text(errors='replace')
    report['serial_pid1_observations'] = dict(
        result=text.count('mt6762_iig_test_result=1 error=0 size=4') == 2,
        cases=text.count('mt6762_iig_test_cases=205 error=0 size=4') == 2,
        done='MT6762_IIG_PROBE_DONE' in text)
    if args.exception_at is not None:
        report['checks'] = dict(exception_uart='!1:' in text,
                                no_xnu='Entering XNU:' not in text and 'Darwin Kernel' not in text)
    elif args.expect_native_refusal:
        report['checks'] = dict(refused='MT6762 PHYSICAL REFUSED: native display/PWM profile' in text,
                                no_xnu='Entering XNU:' not in text and 'Darwin Kernel' not in text)
    elif args.static_memory:
        report['checks'] = dict(refused='MT6762 PHYSICAL REFUSED: no-window' in text,
                                no_xnu='Entering XNU:' not in text and 'Darwin Kernel' not in text)
    else:
        report['checks'] = dict(ram='Validated RAM window 0x00000000d0000000' in text,
                                xnu='Darwin Kernel' in text,
                                pages='MT6762: VM page=16384 hardware page=4096' in text,
                                result=text.count('mt6762_iig_test_result=1 error=0 size=4') == 2,
                                cases=text.count('mt6762_iig_test_cases=205 error=0 size=4') == 2,
                                done='MT6762_IIG_PROBE_DONE' in text)
        if args.display_fixture:
            report['checks'].update(display_admitted='BOOTLOADER DISPLAY VERIFIED' in text,
                                    display_pixels=report['framebuffer_nonzero_bytes'] > 1000,
                                    bounded_display_register_writes=report['display_state']['pwm_writes'] == (8 if args.brightness_pulse else 0) and
                                        report['display_state']['rejected_writes'] == 0)
            if args.native_display:
                log_path=args.output/'kernel-log.bin'
                kernel_text=log_path.read_text(errors='replace') if log_path.exists() else ''
                report['checks'].update(native_display='mt6762-display: inherited OVL0 layer 1' in kernel_text,
                    native_pwm='mt6762-brightness: inherited DISP_PWM0 profile2 validated' in kernel_text,
                    native_pid1='MT6762_IIG_PROBE_DONE' in kernel_text)
                if args.brightness_pulse:
                    report['checks'].update(pwm_dim='MT6762_BRIGHTNESS_DIAGNOSTIC dim_readback=256' in kernel_text,
                        pwm_restored='MT6762_BRIGHTNESS_DIAGNOSTIC restored=1023 done' in kernel_text,
                        pwm_commits=report['display_state']['commits'] == 2)
            if args.two_layer_display:
                report['checks']['opaque_console_pixels'] = report['framebuffer_alpha_opaque']
        if args.visible_console:
            for key in ['result', 'cases', 'done']:
                del report['checks'][key]
            # The page-size log is emitted by XNU before console selection.
            report['checks']['xnu'] = report['checks']['pages']
    report['automated_checks_passed'] = all(report['checks'].values())
    if traced:
        final = report['trace_after']
        report['checks']['trace_initialized_before_execution'] = not report['trace_before']['executed']
        report['checks']['trace_executed'] = final['executed']
        if args.exception_at is not None:
            report['checks']['trace_exception'] = final['phase'] == 255 and final['exception_el'] == 1 and final['elr'] == 0x40083ffc
        elif args.expect_native_refusal:
            report['checks']['trace_refused_native_display'] = final['phase'] == 254 and final['detail'] == 8
        elif args.static_memory:
            report['checks']['trace_refused_no_window'] = final['phase'] == 254 and final['detail'] == 0x208
        else:
            report['checks']['trace_jump_ready'] = final['phase'] == 10 and final['entry'] >= 0xd0000000
        report['automated_checks_passed'] = all(report['checks'].values())
    report['passed'] = None if args.visible_console else report['automated_checks_passed']
    if display_traced:
        expected = 0 if args.exception_at is not None else 8 if args.display_fixture else 1
        report['checks']['display_record_expected_state'] = report['display_after']['state'] == expected
        report['automated_checks_passed'] = all(report['checks'].values())
        report['passed'] = None if args.visible_console else report['automated_checks_passed']
    if pwm_traced:
        expected_states = (2,3) if args.display_fixture else (0,)
        report['checks']['pwm_record_finished'] = report['pwm_after']['state'] in expected_states
        report['automated_checks_passed'] = all(report['checks'].values())
        report['passed'] = None if args.visible_console else report['automated_checks_passed']
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(output=str(args.output), passed=report['passed'], checks=report['checks'])))
    return 0 if report['automated_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
