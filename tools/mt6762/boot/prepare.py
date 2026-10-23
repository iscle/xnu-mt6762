#!/usr/bin/env python3
"""Prepare a local-only XNU boot experiment for the mt6762 QEMU machine.

Mach-O segment/entry and boot_args conventions follow Apple's boot.h and
oosexgang/hackios-xnu-kernel/xnuloader/loader.c. ADT serialization and optional
chained-rebase handling follow joranv1/ios-sailfish/tools/mkpayload.py.
Original implementation, no imported third-party executable code.
Not an Android boot image and not suitable for flashing a physical phone.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import zlib

VIRT = 0xfffffff004000000
PHYS = 0x40000000
MEMORY = 0x20000000
PAGE = 0x4000
TRAMPOLINE = 0x40080000
u32 = lambda *v: struct.pack('<' + 'I' * len(v), *v)
u64 = lambda *v: struct.pack('<' + 'Q' * len(v), *v)
cstr = lambda value: value.encode('ascii') + b'\0'
align = lambda value: (value + PAGE - 1) & ~(PAGE - 1)


def checked(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f'Invalid file range {offset:#x}+{size:#x}')
    return data[offset:offset + size]


def parse_macho(data):
    header = struct.unpack('<8I', checked(data, 0, 32))
    magic, cpu, subtype, kind, count, cmds_size, flags, _ = header
    if magic != 0xfeedfacf or cpu != 0x100000c or (subtype & 0xff) != 0 or kind != 2:
        raise ValueError('Requires a thin arm64 (not arm64e) executable Mach-O')
    checked(data, 32, cmds_size)
    off, end, segments, entry, fixups = 32, 32 + cmds_size, [], None, None
    for _ in range(count):
        cmd, size = struct.unpack('<II', checked(data[:end], off, 8))
        if size < 8 or size % 8:
            raise ValueError('Invalid Mach-O load command size')
        command = checked(data[:end], off, size)
        if cmd == 0x19:
            values = struct.unpack('<II16s4Q4I', checked(command, 0, 72))
            _, _, name, va, vsize, fo, fs, maxprot, prot, nsects, _ = values
            if size != 72 + nsects * 80 or fs > vsize:
                raise ValueError('Invalid segment sections or file size')
            checked(data, fo, fs)
            segments.append(dict(name=name.split(b'\0')[0].decode('ascii'), vmaddr=va,
                                 vmsize=vsize, fileoff=fo, filesize=fs, prot=prot))
        elif cmd == 5:
            flavor, words = struct.unpack('<II', checked(command, 8, 8))
            if flavor != 6 or words != 68 or size != 288 or entry is not None:
                raise ValueError('Unsupported LC_UNIXTHREAD state')
            entry, = struct.unpack('<Q', checked(command, 16 + 32 * 8, 8))
        elif cmd == 0x80000034:
            if size != 16 or fixups is not None:
                raise ValueError('Invalid chained fixups command')
            fixups = struct.unpack('<II', command[8:])
            checked(data, *fixups)
        off += size
    if off != end or entry is None or not segments:
        raise ValueError('Incomplete load commands, segments, or entry')
    active = [s for s in segments if s['vmsize']]
    if not any(s['prot'] & 4 and s['vmaddr'] <= entry < s['vmaddr'] + s['filesize'] for s in active):
        raise ValueError('Entry is outside file-backed executable segments')
    return dict(segments=segments, entry=entry, fixups=fixups, flags=flags)


def rebase(data, macho):
    """Handle only non-authenticated arm64 chained rebases; reject binds/PAC."""
    if not macho['fixups']:
        return 0
    offset, size = macho['fixups']
    fix = checked(data, offset, size)
    version, starts_off, _, _, imports, _, _ = struct.unpack('<7I', checked(fix, 0, 28))
    if version or imports:
        raise ValueError('Chained fixups version/imports unsupported')
    starts = checked(fix, starts_off, len(fix) - starts_off)
    count, = struct.unpack('<I', checked(starts, 0, 4))
    segs = macho['segments']
    if count != len(segs):
        raise ValueError('Chained segment count mismatch')
    image_base = next(s['vmaddr'] for s in segs if s['fileoff'] == 0 and s['filesize'])
    total = 0
    for idx in range(count):
        info, = struct.unpack('<I', checked(starts, 4 + idx * 4, 4))
        if not info:
            continue
        struct_size, page, fmt, segment_offset, _, pages = struct.unpack('<IHHQIH', checked(starts, info, 22))
        body = checked(starts, info, struct_size)
        seg = segs[idx]
        if fmt not in (2, 6) or page not in (0x1000, 0x4000) or segment_offset != seg['vmaddr'] - image_base:
            raise ValueError('Unsupported chained pointer format or segment offset')
        for p in range(pages):
            start, = struct.unpack('<H', checked(body, 22 + p * 2, 2))
            if start == 0xffff:
                continue
            if start & 0x8000:
                raise ValueError('Chained MULTI start unsupported')
            local = p * page + start
            while True:
                if local + 8 > min(seg['filesize'], (p + 1) * page):
                    raise ValueError('Chained pointer leaves its file-backed page')
                loc = seg['fileoff'] + local
                raw, = struct.unpack('<Q', checked(data, loc, 8))
                if raw >> 63:
                    raise ValueError('Chained bind unsupported')
                target = raw & ((1 << 36) - 1)
                high = (raw >> 36) & 0xff
                nxt = (raw >> 51) & 0xfff
                if fmt == 6:
                    target += image_base
                struct.pack_into('<Q', data, loc, target | (high << 56))
                total += 1
                if not nxt:
                    break
                local += nxt * 4
    return total


def node(name, props=(), children=()):
    props = [('name', cstr(name))] + list(props)
    if len({p[0] for p in props}) != len(props):
        raise ValueError('Duplicate ADT property')
    out = bytearray(u32(len(props), len(children)))
    for key, value in props:
        encoded = key.encode('ascii')
        if len(encoded) >= 32 or len(value) >= 0x80000000:
            raise ValueError('ADT property exceeds format limit')
        out += encoded.ljust(32, b'\0') + u32(len(value)) + value
        out += b'\0' * (-len(value) % 4)
    return bytes(out) + b''.join(children)


def nvram():
    image = bytearray(8192)
    for offset, sig, length, name in [(0, 0x5a, 32, 'nvram'), (32, 0x70, 8192 - 32, 'common')]:
        header = bytearray(struct.pack('<BBH12s', sig, 0, length // 16, name.encode()))
        checksum = sum(header)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        header[1] = checksum
        image[offset:offset + 16] = header
    struct.pack_into('<I', image, 20, 1)
    struct.pack_into('<I', image, 16, zlib.adler32(image[20:]))
    return bytes(image)


def load_identity(path):
    """Read only the literal generated root/product arrays; never execute C."""
    text = path.read_text()
    result = {}
    for kind in ('root', 'product'):
        table = re.search(r'identity_' + kind + r'\[\]\s*=\s*\{(.*?)\};', text, re.S)
        payload = re.search(r'identity_' + kind + r'_data\[\]\s*=\s*\{(.*?)\};', text, re.S)
        if not table or not payload:
            raise ValueError('Missing generated identity arrays: ' + kind)
        tokens = payload[1].split(',')
        data = bytes(int(t.strip(), 0) for t in tokens if t.strip())
        props = []
        for name, off, size in re.findall(r'\{\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*\}', table[1]):
            if name == 'name':
                raise ValueError('Identity cannot replace ADT node name')
            props.append((name, checked(data, int(off), int(size))))
        if not props:
            raise ValueError('No properties in identity array')
        result[kind] = props
    if dict(result['root']).get('model') != b'iPhone10,3\0':
        raise ValueError('Identity is not selected iPhone10,3 donor')
    return result


def make_adt(seed, ramdisks=(), framebuffer=False, identity=None):
    if len(seed) != 64:
        raise ValueError('Random seed must be64 bytes')
    chosen = node('chosen', [
        ('random-seed', seed), ('dram-base', u64(PHYS)), ('dram-size', u64(MEMORY)),
        ('debug-enabled', u32(1)), ('psci-method', cstr('smc')),
        ('firmware-version', cstr('mt6762-qemu-experiment')),
        ('display-scale', u32(3)), ('display-rotation', u32(0)),
        ('boot-manifest-hash', hashlib.sha384(b'mt6762-qemu-laboratory-manifest').digest()),
        ('crypto-hash-method', cstr('sha2-384')),
        ('unique-chip-id', u64(0x4d54363736320001)), ('chip-id', u32(0x8015)), ('board-id', u32(6)),
        ('mac-address-wifi0', bytes.fromhex('02005e676201')),
        ('mac-address-bluetooth0', bytes.fromhex('02005e676202')),
        ('nvram-bank-size', u32(8192)), ('nvram-bank-count', u32(1)),
        ('nvram-current-bank', u32(0)), ('nvram-proxy-data', nvram()),
    ], [node('memory-map', [('RAMDisk' + (str(i) if i else ''), u64(*disk))
                            for i, disk in enumerate(ramdisks)])])
    cpu = node('cpu0', [('device_type', cstr('cpu')), ('compatible', cstr('arm,cortex-a53')),
        ('state', cstr('running')), ('reg', u32(0)), ('cpu-id', u32(0)),
        ('cluster-id', u32(0)), ('cluster-type', u32(0)), ('die-cluster-id', u32(0)),
        ('cluster-core-id', u32(0)), ('l2-cache-id', u32(0)),
        ('timebase-frequency', u64(13000000)), ('fixed-frequency', u64(13000000)),
        ('clock-frequency', u64(1800000000)), ('bus-frequency', u64(100000000)),
        ('memory-frequency', u64(100000000)), ('peripheral-frequency', u64(26000000))])
    gic = node('gic', [('device_type', cstr('interrupt-controller')),
        ('compatible', cstr('arm,gic-v3')), ('reg', u64(0, 0x40000, 0x100000, 0x200000)),
        ('virtual-timer-intid', u32(27)), ('redistributor-stride', u32(0x20000))])
    uart = node('uart0', [('device_type', cstr('uart')), ('compatible', cstr('mediatek,mt6577-uart')),
        ('reg', u64(0x05002000, 0x1000)), ('boot-console', u32(1))])
    # MiniIOMobileFramebufferStart publishes its own disp0 node. Duplicating
    # it here makes Apple's framework wait for a second nonexistent display.
    io = node('arm-io', [('device_type', cstr('mt6762-io')), ('compatible', cstr('mt6762-io') + cstr('arm-io')),
        ('#address-cells', u32(2)), ('#size-cells', u32(2)), ('ranges', u64(0, 0x0c000000, 0x08000000))],
        [gic, uart, node('wdt', [('no-pmu', u32(1))])])
    root_props = dict([('compatible', cstr('D22AP') + cstr('iPhone10,3') + cstr('mediatek,mt6762') + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')), ('target-type', cstr('D22')), ('target-sub-type', cstr('D22AP')),
        ('serial-number', cstr('MT6762QEMULAB').ljust(32, b'\0')),
        ('#address-cells', u32(2)), ('#size-cells', u32(2))])
    product = []
    if identity:
        root_props.update(identity['root'])
        root_props['compatible'] += cstr('mediatek,mt6762')
        product = [node('product', identity['product'])]
    return node('device-tree', list(root_props.items()),
        [chosen, node('defaults'), node('options'), node('cpus', children=[cpu]), io] + product)


def boot_args(adt_pa, adt_len, top, cmdline, framebuffer_pa=None):
    line = cmdline.encode('ascii')
    if len(line) >= 608 or b'\0' in line:
        raise ValueError('Boot command line exceeds607 bytes or contains NUL')
    data = bytearray(736)
    struct.pack_into('<HH', data, 0, 2, 2)
    struct.pack_into('<4Q', data, 8, VIRT, PHYS, MEMORY, top)
    if framebuffer_pa:
        struct.pack_into('<6Q', data, 40, framebuffer_pa, 1, 384 * 4, 384, 854, 32)
    struct.pack_into('<Q', data, 96, VIRT + adt_pa - PHYS)
    struct.pack_into('<I', data, 104, adt_len)
    data[108:108 + len(line)] = line
    struct.pack_into('<Q', data, 728, MEMORY)
    return data


def validate_regions(regions):
    ordered = sorted(regions, key=lambda r: r['addr'])
    for r in ordered:
        if r['size'] <= 0 or r['addr'] < PHYS or r['addr'] + r['size'] > PHYS + MEMORY:
            raise ValueError('Region outside QEMU RAM: ' + r['name'])
    for a, b in zip(ordered, ordered[1:]):
        if a['addr'] + a['size'] > b['addr']:
            raise ValueError('Overlapping regions: ' + a['name'] + ' / ' + b['name'])


def trampoline(ba_pa, entry_pa):
    return f'''/* QEMU-only AArch64 Linux Image handoff; no stack or relocation. */
.section .text,"ax"
.global _start
_start:
    b start
    .long 0
    .quad 0x80000
    .quad image_end - _start
    .quad 0xa
    .quad 0, 0, 0
    .long 0x644d5241
    .long 0
start:
    msr daifset, #15
    ldr x1, =0x11002000
    adr x2, message
1:  ldrb w3, [x2], #1
    cbz w3, 3f
2:  ldr w4, [x1, #0x14]
    tbz w4, #5, 2b
    str w3, [x1]
    b 1b
3:  dsb sy
    ic iallu
    dsb sy
    isb
    ldr x0, ={ba_pa:#x}
    ldr x9, ={entry_pa:#x}
    mov x1, xzr
    mov x2, xzr
    mov x3, xzr
    br x9
message:
    .asciz "mt6762 loader: entering XNU at {entry_pa:#x} boot_args={ba_pa:#x}\\r\\n"
    .balign 8
    .ltorg
image_end:
'''


def main():
    global MEMORY
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--clang', type=Path, required=True)
    p.add_argument('--objcopy', type=Path, required=True)
    p.add_argument('--qemu', type=Path, required=True)
    p.add_argument('--linux-dtb', type=Path, required=True)
    p.add_argument('--ramdisk', type=Path, action='append', default=[],
                   help='Raw filesystem or mockfs executable; repeat for md0, md1, ...')
    p.add_argument('--memory-mib', type=int, default=512,
                   help='Emulated RAM only; actual phone RAM remains unknown (default512MiB)')
    p.add_argument('--framebuffer', action='store_true',
                   help='Synthetic384x854 BGRA backing RAM, not a MediaTek display-controller model')
    p.add_argument('--identity-header', type=Path,
                   help='Generated donor identity.h containing root/product literal arrays')
    p.add_argument('--cmdline', default='debug=0x14e serial=3 cpus=1 keepsyms=1 -v -enable_kprintf_spam')
    a = p.parse_args()
    if not 256 <= a.memory_mib <= 4096 or a.memory_mib % 32:
        raise ValueError('Emulated RAM must be256..4096MiB in32MiB multiples')
    MEMORY = a.memory_mib * 1024 * 1024
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    raw = a.kernel.read_bytes()
    data = bytearray(raw)
    m = parse_macho(data)
    nfix = rebase(data, m)
    regions, blobs = [], []
    for i, seg in enumerate(m['segments']):
        if not seg['vmsize']:
            continue
        pa = PHYS + seg['vmaddr'] - VIRT
        if pa % PAGE or seg['vmaddr'] < VIRT:
            raise ValueError('Segment is not16K aligned or lies below virtual base')
        region = {'name': seg['name'], 'addr': pa, 'size': align(seg['vmsize']),
                  'file': str(out / f'segment-{i:02d}.bin')}
        regions.append(region)
        blobs.append((region, checked(data, seg['fileoff'], seg['filesize'])))
    cursor = max(r['addr'] + r['size'] for r in regions)
    ramdisk_info = []
    ramdisk_pairs = []
    def skip_linux_dtb(start, size):
        if start < PHYS + 0x8200000 and start + size > PHYS + 0x8000000:
            return PHYS + 0x8200000
        return start
    for index, disk in enumerate(a.ramdisk):
        original_size = disk.stat().st_size
        size = align(original_size)
        if not size or size >= MEMORY:
            raise ValueError('RAM disk is empty or exceeds emulated RAM')
        cursor = skip_linux_dtb(cursor, size)
        region = dict(name='RAMDisk' + (str(index) if index else ''), addr=cursor, size=size,
                      source_size=original_size, file=str(out / f'ramdisk-{index}.bin'))
        validate_regions(regions + [region])
        regions.append(region)
        blobs.append((region, disk))
        ramdisk_pairs.append((cursor, size))
        ramdisk_info.append(dict(source=str(disk.resolve()), addr=hex(cursor), size=size))
        cursor += size
        if not any(arg.startswith('rd=') for arg in shlex.split(a.cmdline)):
            a.cmdline += ' rd=md0'
    framebuffer = None
    if a.framebuffer:
        size = align(384 * 854 * 4)
        cursor = skip_linux_dtb(cursor, size)
        framebuffer = dict(name='synthetic-framebuffer', addr=cursor, size=size,
                           file=str(out / 'framebuffer.bin'), width=384, height=854, stride=1536,
                           format='BGRA8888', simulated_ram_only=True)
        regions.append(framebuffer)
        blobs.append((framebuffer, bytes(size)))
        cursor += size
    identity = load_identity(a.identity_header) if a.identity_header else None
    adt = make_adt(os.urandom(64), ramdisk_pairs, a.framebuffer, identity)
    adt_pa = skip_linux_dtb(cursor, align(len(adt)) + PAGE)
    ba_pa = align(adt_pa + len(adt))
    top = ba_pa + PAGE
    for name, pa, payload in [('device-tree', adt_pa, adt), ('boot-args', ba_pa, boot_args(adt_pa, len(adt), top, a.cmdline,
                                                                                  framebuffer['addr'] if framebuffer else None))]:
        region = dict(name=name, addr=pa, size=align(len(payload)), file=str(out / (name + '.bin')))
        regions.append(region)
        blobs.append((region, payload))
    reserved = [dict(name='QEMU bootstub', addr=PHYS, size=0x10000),
                dict(name='Linux trampoline', addr=TRAMPOLINE, size=0x10000),
                dict(name='QEMU Linux DTB reservation', addr=PHYS + 0x8000000, size=0x200000)]
    validate_regions(regions + reserved)
    entry_pa = PHYS + m['entry'] - VIRT
    for region, payload in blobs:
        # Explicit zero-fill guarantees BSS and alignment padding are deterministic.
        if isinstance(payload, Path):
            if payload.resolve() == Path(region['file']).resolve():
                raise ValueError('RAM disk output would overwrite its source')
            hashed = hashlib.sha256()
            copied = 0
            with payload.open('rb') as src, Path(region['file']).open('wb') as dst:
                while chunk := src.read(8 * 1024 * 1024):
                    copied += len(chunk)
                    if copied > region['source_size']:
                        raise ValueError('RAM disk grew while being read')
                    dst.write(chunk)
                    hashed.update(chunk)
                if copied != region['source_size']:
                    raise ValueError('RAM disk changed size while being read')
                dst.write(bytes(region['size'] - copied))
            region['source_sha256'] = hashed.hexdigest()
        else:
            Path(region['file']).write_bytes(payload + bytes(region['size'] - len(payload)))
    (out / 'trampoline.S').write_text(trampoline(ba_pa, entry_pa))
    elf = out / 'trampoline.elf'
    image = out / 'trampoline.Image'
    subprocess.run([str(a.clang), '--target=aarch64-none-elf', '-march=armv8-a', '-nostdlib', '-fuse-ld=lld',
                    '-Wl,-Ttext=0x40080000', '-Wl,--entry=_start', '-Wl,--build-id=none', str(out / 'trampoline.S'), '-o', str(elf)], check=True)
    subprocess.run([str(a.objcopy), '-O', 'binary', '-j', '.text', str(elf), str(image)], check=True)
    if image.stat().st_size > 0x10000:
        raise ValueError('Trampoline exceeded reserved size')
    command = [str(a.qemu.resolve()), '-M', 'mt6762', '-accel', 'tcg', '-cpu', 'cortex-a53', '-smp', '1',
               '-m', f'{a.memory_mib}M', '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-no-reboot',
               '-kernel', str(image), '-dtb', str(a.linux_dtb.resolve())]
    for r in regions:
        if ',' in r['file']:
            raise ValueError('QEMU loader filenames must not contain commas')
        command += ['-device', f'loader,file={r["file"]},addr={r["addr"]:#x},force-raw=on']
    (out / 'run.sh').write_text('#!/bin/sh\n# Local emulation only; no device writes. Extra arguments are passed to QEMU.\nexec ' + shlex.join(command) + ' "$@"\n')
    (out / 'run.sh').chmod(0o755)
    manifest = dict(kernel=str(a.kernel.resolve()), kernel_sha256=hashlib.sha256(raw).hexdigest(),
                    entry_va=hex(m['entry']), entry_pa=hex(entry_pa), virt_base=hex(VIRT), phys_base=hex(PHYS),
                    ram_size=MEMORY, vm_page_size=PAGE, hardware_page_size=4096,
                    boot_args_pa=hex(ba_pa), adt_pa=hex(adt_pa), top_of_kernel_data=hex(top),
                    chained_rebases=nfix, ramdisk=ramdisk_info, framebuffer=framebuffer,
                    identity_header_sha256=hashlib.sha256(a.identity_header.read_bytes()).hexdigest() if a.identity_header else None,
                    regions=regions, reserved=reserved, command=command,
                    limits=['QEMU bring-up only; not a phone boot image.',
                            'RAM disk attached; userland boot still requires runtime verification.' if ramdisk_info else 'No root filesystem attached.',
                            'Root/product metadata from donor when identity header supplied; serial/ECID/MAC are synthetic lab values.',
                            '16K software VM/4K hardware requires an appropriately configured XNU.'])
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k not in ('regions', 'command', 'reserved')}, indent=2))


if __name__ == '__main__':
    main()
