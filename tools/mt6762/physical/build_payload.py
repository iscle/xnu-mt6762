#!/usr/bin/env python3
"""Build a physical XNU diagnostic or eMMC desktop bootstrap; no device commands."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'boot'))
import prepare
import trace_record
import display_record
import pwm_record
import peripheral_record
import desktop_ramdisk


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode_adt(data, offset=0, path=''):
    props, children = struct.unpack_from('<II', data, offset)
    offset += 8
    values, positions = {}, {}
    for _ in range(props):
        name = data[offset:offset+32].split(b'\0')[0].decode('ascii')
        size, = struct.unpack_from('<I', data, offset+32)
        offset += 36
        if name in values or size > len(data)-offset:
            raise ValueError('invalid generated ADT')
        values[name] = data[offset:offset+size]
        positions[name] = offset
        offset += (size+3)&~3
    name = values.pop('name').rstrip(b'\0').decode('ascii')
    path += '/' + name
    all_positions = {path+'/'+k:v for k,v in positions.items()}
    descendants = []
    for _ in range(children):
        child, offset, child_positions = decode_adt(data, offset, path)
        descendants.append(child)
        all_positions.update(child_positions)
    return dict(name=name, props=values, children=descendants), offset, all_positions


def encode_adt(tree):
    return prepare.node(tree['name'], list(tree['props'].items()),
                        [encode_adt(child) for child in tree['children']])


CHARGER_SETUP_FLAGS = ('dma-direct','i2c-pads-verified','i2c5-verified',
                       'charger-inherited-probe','charger-setup-only')
CHARGER_READONLY_FLAGS = CHARGER_SETUP_FLAGS[:-1] + ('charger-readonly-probe',)
# Reviewed frozen kernel: secondary EL2 descent, firmware queries and cache
# handoff; original-entry tests and an eight-core QEMU run passed.
SMP_KERNELS = {
    '1d2310dfe3cc89fa29fadc896544503d89eedc01269c85d35278afa46f8f4f20',
    # HakiOS kernel56: same reviewed start.s/psci_smp.c as kernel54;
    # fresh build passed, QEMU observed8/8 CPUs and205 IIG runtime checks.
    # This pin admits packaging, not physical8-core validation.
    'bcc01522daf9bb430e8fd8df3d2b29a34bc3bf52674b978d936520eee1def60b',
}
# Capture34 exhausted the old20ms software wait before the inherited DDR
# controller's approximately109ms data timeout. Allow its existing hardware
# timeout/error reporting inside the protocol's bounded1s software envelope.
# No controller timeout register is changed. See storage/DATA-TIMEOUT.rst.
PHYSICAL_MSDC_TIMEOUT_US = 1000000


def require_smp_kernel(kernel,cpus):
    if type(cpus) is not int or cpus not in (1,2,4,8):
        raise ValueError('physical CPU count must be1,2,4or8')
    if cpus>1 and sha(kernel) not in SMP_KERNELS:
        raise ValueError('multicore boot requires a reviewed frozen secondary-entry kernel')


def charger_setup_properties():
    """Clear grants until live entry admission; never authorize transactions."""
    props={name:prepare.u32(0) for name in CHARGER_SETUP_FLAGS}
    props.update({name:prepare.u32(value) for name,value in
        {'i2c-parent-index':2,'i2c-parent-hz':124800000,'i2c5-hz':100000}.items()})
    return props


def require_charger_setup_kernel(kernel,requested):
    if requested and b'MT6762_I2C_SETUP_ONLY bus=%u strict=%u transactions=0\n\0' not in kernel:
        raise ValueError('native charger setup requires a kernel with setup-only transaction blocking')


def charger_readonly_properties():
    """Six bounded PSC register reads after live admission; no charger control."""
    props=charger_setup_properties()
    del props['charger-setup-only']
    props['charger-readonly-probe']=prepare.u32(0)
    return props


def require_charger_readonly_kernel(kernel,requested):
    if requested and (b'MT6762_PSC_READONLY_ADMITTED transactions=6\n\0' not in kernel or
                      b'MT6762_PSC_PROBE pass=' not in kernel):
        raise ValueError('native charger reads require the bounded six-transaction kernel implementation')


def trial_bootarg(kernel,seconds,refresh_watchdog):
    """Opt in only when this kernel implements the bounded stop-feed path."""
    if type(seconds) is not int or (seconds != 0 and not 60 <= seconds <= 1800):
        raise ValueError('trial seconds must be0 or60..1800')
    if not seconds:
        return ''
    if not refresh_watchdog:
        raise ValueError('trial deadline requires inherited watchdog servicing')
    if b'MT6762_TRIAL armed seconds=' not in kernel:
        raise ValueError('trial deadline requires a kernel with the stop-feed implementation')
    return ' mt6762_trial_seconds='+str(seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel', 'template', 'llvm', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    root = parser.add_mutually_exclusive_group(required=True)
    root.add_argument('--diagnostic', type=Path, help='standalone project PID1 Mach-O')
    root.add_argument('--bootstrap-apfs', type=Path, help='small APFS root containing the desktop bootstrap and helpers')
    parser.add_argument('--ios-system-slice', nargs=2, type=lambda v:int(v,0),
                        metavar=('START','COUNT'), help='read-only 512-byte sector extent inside captured userdata')
    parser.add_argument('--native-display', action='store_true',
                        help='require measured LK display/PWM admission and emit its native handoff')
    parser.add_argument('--cpus',type=int,choices=(1,2,4,8),default=1,
                        help='requires exact live PSCI/A53 topology and reviewed kernel for2/4/8; default1')
    parser.add_argument('--brightness-pulse', action='store_true',
                        help='opt in to the kernel dim/restore diagnostic before PID1')
    parser.add_argument('--probe-peripherals', action='store_true',
                        help='passively snapshot audited touch/storage/key/watchdog registers; grants no ownership')
    parser.add_argument('--expand-memory', action='store_true',
                        help='extend the diagnostic RAM window to the next reserved region, bounded by CPU PA width')
    parser.add_argument('--native-touch-probe',action='store_true',
                        help='admit measured inherited I2C0 for version/DMA then polling; never changes touch rail/reset')
    parser.add_argument('--refresh-watchdog',action='store_true',help='refresh the measured inherited watchdog without reconfiguring it')
    parser.add_argument('--trial-seconds',type=int,default=0,
                        help='stop inherited watchdog refresh after60..1800seconds; default0 disables; reset/retention not guaranteed')
    parser.add_argument('--native-pwrap-probe',action='store_true',
                        help='admit inherited LK WACS2 for bounded read-only PMIC/rail observations')
    parser.add_argument('--native-msdc-probe',action='store_true',
                        help='admit exact synchronous LK eMMC handoff; kernel must verify rails/CMD13/EXT_CSD')
    parser.add_argument('--native-buttons-probe',action='store_true',
                        help='read-only power/volume polling through measured PWRAP and inherited keypad')
    charger=parser.add_mutually_exclusive_group()
    charger.add_argument('--native-charger-setup-probe',action='store_true',
                        help='admit measured inherited I2C5 for setup/readbacks only; no PSC or bias transactions')
    charger.add_argument('--native-charger-readonly-probe',action='store_true',
                        help='admit measured inherited I2C5 for six PSC register reads; no charging control')
    args = parser.parse_args()
    if args.brightness_pulse and not args.native_display:
        parser.error('--brightness-pulse requires --native-display')
    if (args.native_touch_probe or args.refresh_watchdog or args.native_pwrap_probe) and not (args.native_display and args.probe_peripherals):
        parser.error('touch/watchdog/PWRAP requires native display and passive peripheral capture')
    if args.native_msdc_probe and not args.native_pwrap_probe:
        parser.error('native MSDC requires the read-only PWRAP probe')
    if args.native_buttons_probe and not args.native_pwrap_probe:
        parser.error('native buttons require the read-only PWRAP probe')
    if args.native_charger_setup_probe and not args.native_pwrap_probe:
        parser.error('native charger setup requires the read-only PWRAP probe')
    if args.native_charger_readonly_probe and not args.native_pwrap_probe:
        parser.error('native charger reads require the read-only PWRAP probe')
    if bool(args.bootstrap_apfs) != bool(args.ios_system_slice):
        parser.error('--bootstrap-apfs and --ios-system-slice require each other')
    if args.bootstrap_apfs and not (args.native_msdc_probe and args.expand_memory and args.refresh_watchdog):
        parser.error('desktop bootstrap requires native MSDC, expanded memory and watchdog servicing')
    ios_slice = desktop_ramdisk.validate_slice(*args.ios_system_slice) if args.ios_system_slice else None
    out = args.out.resolve()
    if out.exists():
        parser.error('output must be new')
    source_paths = [HERE/name for name in ('start.S','loader.c','loader.ld',
        'fdt_handoff.c','fdt_handoff.h','diagnostic_console.h','loader_trace.h',
        'trace_record.py','display_probe.h','display_record.py','pwm_probe.h','pwm_record.py',
        'native_display.h','native_storage.h','peripheral_probe.h','peripheral_record.py','peripheral-registers.json',
        'build_payload.py','bootimg.py','desktop_ramdisk.py')]
    source_paths += [HERE/'psci/psci_fdt.c',HERE/'psci/psci_fdt.h']
    source_paths += [Path(prepare.__file__), HERE.parent/'hardware/display-touch/mt6762_display_core.h']
    source_paths += [HERE.parent/'hardware/display-touch/mt6762_touch_entry.h']
    source_paths += [HERE.parent/'hardware/power/mt6762_pwrap_entry.h']
    source_paths += [HERE.parent/'hardware/power/mt6762_keys_entry.h']
    source_paths += [HERE.parent/'hardware/power/mt6762_charger_entry.h']
    source_paths += [HERE.parents[2]/'bsd/dev/mt6762_msdc_clock.h']
    sources_before = {os.path.relpath(p,HERE.parent):sha(p.read_bytes()) for p in source_paths}
    original_kernel = args.kernel.read_bytes()
    require_smp_kernel(original_kernel,args.cpus)
    require_charger_setup_kernel(original_kernel,args.native_charger_setup_probe)
    require_charger_readonly_kernel(original_kernel,args.native_charger_readonly_probe)
    trial_arg = trial_bootarg(original_kernel,args.trial_seconds,args.refresh_watchdog)
    root_path = args.bootstrap_apfs or args.diagnostic
    if args.bootstrap_apfs and root_path.stat().st_size > desktop_ramdisk.MAX_BOOTSTRAP_BYTES:
        raise ValueError('bootstrap exceeds32MiB')
    original_diagnostic = root_path.read_bytes()
    root_info = desktop_ramdisk.validate_bootstrap(original_diagnostic) if args.bootstrap_apfs else dict(format='mach-o')
    trace_identity = hashlib.sha256(os.urandom(32) + original_kernel +
        json.dumps(sources_before, sort_keys=True).encode()).digest()
    template_sha = sha(args.template.read_bytes())
    kernel = bytearray(original_kernel)
    macho = prepare.parse_macho(kernel)
    rebases = prepare.rebase(kernel, macho)
    segments = []
    for segment in macho['segments']:
        if not segment['vmsize']:
            continue
        offset = segment['vmaddr'] - prepare.VIRT
        if offset < 0 or offset % prepare.PAGE or offset + segment['vmsize'] > 0x18000000:
            raise ValueError('kernel outside bounded diagnostic window')
        segments.append(dict(offset=offset, fileoff=segment['fileoff'],
                             filesize=segment['filesize'], vmsize=segment['vmsize']))
    ordered = sorted(segments, key=lambda segment:segment['offset'])
    for left, right in zip(ordered, ordered[1:]):
        if left['offset']+left['vmsize'] > right['offset']:
            raise ValueError('overlapping kernel segments')
    diagnostic = original_diagnostic
    if not args.bootstrap_apfs:
        prepare.parse_macho(diagnostic)
    ramdisk_offset = prepare.align(max(s['offset']+s['vmsize'] for s in segments))
    ramdisk_size = prepare.align(len(diagnostic))
    diagnostic += bytes(ramdisk_size-len(diagnostic))
    adt_offset = ramdisk_offset + ramdisk_size
    prepare.PHYS = 0xd0000000  # Template only; runtime replaces it after FDT admission.
    prepare.MEMORY = 0x20000000
    tree, _, _ = decode_adt(prepare.make_adt(__import__('os').urandom(64),
        [(prepare.PHYS+ramdisk_offset, ramdisk_size)], cpus=args.cpus))
    tree['props']['serial-number'] = b'MT6762DIAGNOSTIC\0'.ljust(32,b'\0')
    chosen = next(child for child in tree['children'] if child['name']=='chosen')
    if chosen['props'].get('psci-method') != b'smc\0':
        raise ValueError('physical CPU startup requires the SMC conduit')
    cpu_nodes=next(child for child in tree['children'] if child['name']=='cpus')['children']
    expected_mpids=[(index//4)*0x100+index%4 for index in range(args.cpus)]
    if (len(cpu_nodes)!=args.cpus or
        [child['props'].get('reg') for child in cpu_nodes]!=[prepare.u32(v) for v in expected_mpids]):
        raise ValueError('generated CPU topology does not match the runtime admission profile')
    chosen['props']['firmware-version'] = b'mt6762-physical-diagnostic\0'
    if args.bootstrap_apfs:
        chosen['props']['firmware-version'] = b'mt6762-physical-desktop-bootstrap\0'
    chosen['props']['boot-manifest-hash'] = hashlib.sha384(kernel).digest()
    for key in ('unique-chip-id', 'mac-address-wifi0', 'mac-address-bluetooth0'):
        chosen['props'].pop(key, None)
    native_flags = ('native-io','display-verified','display-reserved','display-dma-physical',
        'display-pipeline-verified','brightness-verified','brightness-pins-verified','brightness-parent-verified')
    if args.native_display:
        # All grants start clear. Only the live loader admission patches them.
        props = {name:prepare.u32(0) for name in native_flags}
        props.update({k:prepare.u32(v) for k,v in {'version':1,'display-profile':2,
            'brightness-profile':2,'fb-width':384,'fb-height':854,'fb-stride':1536,
            'fb-format':1,'fb-ovl-layer':1}.items()})
        props.update({k:prepare.u64(v) for k,v in {'fb-phys':0,'fb-size':0x144000,
            'fb-reserved-base':0,'fb-reserved-size':0}.items()})
        touch_flags=('dma-direct','i2c-pads-verified','i2c0-verified','touch-inherited-probe')
        if args.native_touch_probe:
            props.update({name:prepare.u32(0) for name in touch_flags})
            props.update({k:prepare.u32(v) for k,v in {'i2c-parent-index':2,'i2c-parent-hz':124800000,
                'i2c0-hz':100000,'touch-bus':0,'touch-address':0x3b,'touch-max-x':384,'touch-max-y':854}.items()})
        if args.native_charger_setup_probe:
            props.update(charger_setup_properties())
        if args.native_charger_readonly_probe:
            props.update(charger_readonly_properties())
        if args.refresh_watchdog:props['watchdog-refresh-owned']=prepare.u32(0)
        pwrap_flags=('pwrap-verified','pwrap-inherited-probe')
        if args.native_pwrap_probe:
            props.update({name:prepare.u32(0) for name in pwrap_flags})
            props['pwrap-profile']=prepare.u32(2)
        keys_flags=('keys-inherited-probe','keypad-verified')
        if args.native_buttons_probe:
            props.update({name:prepare.u32(0) for name in keys_flags})
        msdc_flags=('msdc-owned','msdc-inherited-verified','msdc-irq-owned','msdc-clock-owned',
            'msdc-pads-owned','msdc-rails-preserved','msdc-tuning-preserved',
            'msdc-card-quiesced','msdc-writes-drained','msdc-sector-addressed',
            'msdc-ocr-verified','msdc-handoff-producer-version')
        # Same uint32 field order as native_storage.h; values begin unavailable.
        msdc_values=('msdc-sector-count','msdc-ocr','msdc-rca','msdc-cfg','msdc-sdc-cfg',
            'msdc-pad-drive','msdc-hclk-hz','msdc-card-clock-hz','msdc-pll-con0',
            'msdc-pll-con1','msdc-pll-power','msdc-mainpll-con0','msdc-mainpll-con1',
            'msdc-mainpll-power')+tuple(f'msdc-top-tune-{i}' for i in range(12))+tuple(
            f'msdc-controller-tune-{i}' for i in range(18))
        if args.native_msdc_probe:
            assert len(msdc_values)==44
            props.update({name:prepare.u32(0) for name in msdc_flags+msdc_values})
            props['msdc-timeout-us']=prepare.u32(PHYSICAL_MSDC_TIMEOUT_US)
        if ios_slice:
            props['ios-system-slice']=prepare.u32(0)
            props['ios-system-start-sector']=prepare.u64(ios_slice['start_sector'])
            props['ios-system-sector-count']=prepare.u64(ios_slice['sector_count'])
        chosen['children'].append(dict(name='mt6762-handoff',props=props,children=[]))
    adt = encode_adt(tree)
    _, end, positions = decode_adt(adt)
    assert end == len(adt)
    if ((b'mt6762-handoff' in adt and not args.native_display) or
        b'lab-fixture' in adt or b'qemu' in adt.lower()):
        raise ValueError('laboratory-only metadata in physical ADT')
    args_offset = prepare.align(adt_offset+len(adt))
    top_offset = prepare.align(args_offset+736)
    command = f'debug=0x14e serial=3 keepsyms=1 -v -enable_kprintf_spam rd=md0 cpus={args.cpus} mt6762_iig_selftest=1'
    if ios_slice:
        # Keep fatal exception tracing for every process, but limit failed-BSD
        # syscall printing to the small bootstrap. SpringBoard performs many
        # expected ENOENT probes; capture30 showed these filling the physical
        # console during startup. The exception tracer ignores systrace_name.
        command += ' systrace=1 systrace_name=launchd applog=1'
    if args.brightness_pulse:
        command += ' mt6762_brightness_diagnostic=1'
    command += trial_arg
    boot_args = prepare.boot_args(prepare.PHYS+adt_offset,len(adt),prepare.PHYS+top_offset,command)
    if top_offset > prepare.MEMORY:
        raise ValueError('diagnostic objects exceed target window')
    out.mkdir(parents=True)
    blobs = {'xnu':bytes(kernel), 'diagnostic':diagnostic, 'adt':adt, 'args':boot_args}
    for name,data in blobs.items():
        (out/(name+'.bin')).write_bytes(data)
    constants = dict(SEGMENT_COUNT=len(segments), ENTRY_OFFSET=macho['entry']-prepare.VIRT,
        RAMDISK_OFFSET=ramdisk_offset,RAMDISK_SIZE=ramdisk_size,ADT_OFFSET=adt_offset,
        ADT_SIZE=len(adt),ARGS_OFFSET=args_offset,TOP_OFFSET=top_offset,
        ADT_DRAM_PATCH=positions['/device-tree/chosen/dram-base'],
        ADT_DRAM_SIZE_PATCH=positions['/device-tree/chosen/dram-size'],
        ADT_RAMDISK_PATCH=positions['/device-tree/chosen/memory-map/RAMDisk'],
        SERIAL_PATCH=108+command.index('serial=3')+len('serial='))
    constants['NATIVE_DISPLAY'] = int(args.native_display)
    constants['CPUS'] = args.cpus
    constants['PROBE_PERIPHERALS'] = int(args.probe_peripherals)
    constants['EXPAND_MEMORY'] = int(args.expand_memory)
    constants['NATIVE_TOUCH_PROBE']=int(args.native_touch_probe)
    constants['REFRESH_WATCHDOG']=int(args.refresh_watchdog)
    constants['NATIVE_PWRAP_PROBE']=int(args.native_pwrap_probe)
    constants['NATIVE_MSDC_PROBE']=int(args.native_msdc_probe)
    constants['NATIVE_BUTTONS_PROBE']=int(args.native_buttons_probe)
    constants['NATIVE_CHARGER_SETUP_PROBE']=int(args.native_charger_setup_probe)
    constants['NATIVE_CHARGER_READONLY_PROBE']=int(args.native_charger_readonly_probe)
    constants['IOS_SYSTEM_SLICE']=int(ios_slice is not None)
    if ios_slice:
        constants['IOS_SYSTEM_START']=ios_slice['start_sector']
        constants['IOS_SYSTEM_COUNT']=ios_slice['sector_count']
        constants['ADT_IOS_SLICE_PATCH']=positions['/device-tree/chosen/mt6762-handoff/ios-system-slice']
    if args.native_display:
        native_path='/device-tree/chosen/mt6762-handoff/'
        constants.update({k:positions[native_path+name] for k,name in (
            ('ADT_FB_PHYS_PATCH','fb-phys'),('ADT_FB_BASE_PATCH','fb-reserved-base'),
            ('ADT_FB_SIZE_PATCH','fb-reserved-size'))})
    header = '#include <stdint.h>\nstruct payload_segment {uint64_t offset,fileoff,filesize,vmsize;};\n'
    header += ''.join(f'#define PAYLOAD_{k} UINT64_C({v:#x})\n' for k,v in constants.items())
    header += 'static const struct payload_segment payload_segments[] = {\n'
    header += ''.join(' {'+','.join(f'UINT64_C({s[k]:#x})' for k in ('offset','fileoff','filesize','vmsize'))+'},\n' for s in segments)
    header += '};\n'
    if args.native_display:
        header += 'static const unsigned payload_native_flags[] = {'
        header += ','.join(str(positions[native_path+name]) for name in native_flags)+'};\n'
        if args.native_touch_probe:
            header+='static const unsigned payload_touch_flags[] = {'+','.join(str(positions[native_path+name]) for name in touch_flags)+'};\n'
        if args.refresh_watchdog:
            header+=f'#define PAYLOAD_ADT_WATCHDOG_PATCH {positions[native_path+"watchdog-refresh-owned"]}\n'
        if args.native_pwrap_probe:
            header+='static const unsigned payload_pwrap_flags[] = {'+','.join(str(positions[native_path+name]) for name in pwrap_flags)+'};\n'
        if args.native_buttons_probe:
            header+='static const unsigned payload_keys_flags[] = {'+','.join(str(positions[native_path+name]) for name in keys_flags)+'};\n'
        if args.native_charger_setup_probe:
            header+='static const unsigned payload_charger_setup_flags[] = {'+','.join(str(positions[native_path+name]) for name in CHARGER_SETUP_FLAGS)+'};\n'
        if args.native_charger_readonly_probe:
            header+='static const unsigned payload_charger_readonly_flags[] = {'+','.join(str(positions[native_path+name]) for name in CHARGER_READONLY_FLAGS)+'};\n'
        if args.native_msdc_probe:
            for kind,names in (('flags',msdc_flags),('values',msdc_values)):
                header+=f'static const unsigned payload_msdc_{kind}[] = '+'{'+','.join(str(positions[native_path+name]) for name in names)+'};\n'
    (out/'payload_layout.h').write_text(header)
    assembly = '.section .payload,"a"\n'
    for name in blobs:
        path = str(out/(name+'.bin'))
        if any(c in path for c in '\n"\\'):
            raise ValueError('unsupported assembly input path')
        assembly += f'.balign 16\n.global {name}_blob\n{name}_blob:\n.incbin "{path}"\n'
    (out/'payload.S').write_text(assembly)
    (out/'trace.bin').write_bytes(trace_record.initialized(trace_identity))
    trace_assembly = '.section .trace,"aw"\n.balign 64\n.global physical_trace\nphysical_trace:\n'
    trace_assembly += '.incbin "' + str(out/'trace.bin') + '"\n'
    (out/'display.bin').write_bytes(display_record.initialized(trace_identity))
    trace_assembly += '.section .display_trace,"aw"\n.balign 64\n.global physical_display\nphysical_display:\n'
    trace_assembly += '.incbin "' + str(out/'display.bin') + '"\n'
    (out/'pwm.bin').write_bytes(pwm_record.initialized(trace_identity))
    trace_assembly += '.section .pwm_trace,"aw"\n.balign 64\n.global physical_pwm\nphysical_pwm:\n'
    trace_assembly += '.incbin "' + str(out/'pwm.bin') + '"\n'
    (out/'peripherals.bin').write_bytes(peripheral_record.initialized(trace_identity))
    trace_assembly += '.section .peripheral_trace,"aw"\n.balign 64\n.global physical_peripherals\nphysical_peripherals:\n'
    trace_assembly += '.incbin "' + str(out/'peripherals.bin') + '"\n'
    (out/'trace.S').write_text(trace_assembly)
    clang = str(args.llvm/'clang')
    common = [clang,'--target=aarch64-none-elf','-mcpu=cortex-a53','-mgeneral-regs-only',
              '-mstrict-align','-ffixed-x28',
              '-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-pic','-O2',
              '-Wall','-Wextra','-Werror','-I'+str(HERE),'-I'+str(out)]
    commands = []
    for source in (HERE/'start.S',HERE/'loader.c',HERE/'fdt_handoff.c',HERE/'psci/psci_fdt.c',out/'payload.S',out/'trace.S'):
        command_line = common+['-c',str(source),'-o',str(out/(source.stem+'.o'))]
        commands.append(command_line);subprocess.run(command_line,check=True)
    command_line = [str(args.llvm/'ld.lld'),'-T',str(HERE/'loader.ld'),'-o',str(out/'loader.elf')]
    command_line += [str(out/(name+'.o')) for name in ('start','loader','fdt_handoff','psci_fdt','payload','trace')]
    commands.append(command_line);subprocess.run(command_line,check=True)
    command_line = [str(args.llvm/'llvm-objcopy'),'-O','binary',str(out/'loader.elf'),str(out/'Image')]
    commands.append(command_line);subprocess.run(command_line,check=True)
    raw_image = (out/'Image').read_bytes()
    if raw_image[trace_record.OFFSET:trace_record.OFFSET + trace_record.SIZE] != trace_record.initialized(trace_identity):
        raise ValueError('trace record does not match fixed source Image offset')
    if raw_image[display_record.OFFSET:display_record.OFFSET + display_record.SIZE] != display_record.initialized(trace_identity):
        raise ValueError('display record does not match fixed source Image offset')
    if raw_image[pwm_record.OFFSET:pwm_record.OFFSET + pwm_record.SIZE] != pwm_record.initialized(trace_identity):
        raise ValueError('PWM record does not match fixed source Image offset')
    if raw_image[peripheral_record.OFFSET:peripheral_record.OFFSET + peripheral_record.SIZE] != peripheral_record.initialized(trace_identity):
        raise ValueError('Peripheral record does not match fixed source Image offset')
    # Empty Android newc archive; XNU's actual root is embedded in Image.
    name=b'TRAILER!!!\0'; fields=[0,0,0,0,1,0,0,0,0,0,0,len(name),0]
    cpio=b'070701'+b''.join(f'{field:08x}'.encode() for field in fields)+name
    cpio+=bytes(-len(cpio)%4)
    (out/'unused-initramfs.gz').write_bytes(gzip.compress(cpio,mtime=0))
    image_path=out/'mt6762-xnu-diagnostic-boot.img'
    command_line=[sys.executable,str(HERE/'bootimg.py'),'pack','--template',str(args.template),
        '--kernel',str(out/'Image'),'--gzip-kernel','--ramdisk',str(out/'unused-initramfs.gz'),'--output',str(image_path)]
    commands.append(command_line);subprocess.run(command_line,check=True)
    sources_after = {os.path.relpath(p,HERE.parent):sha(p.read_bytes()) for p in source_paths}
    if sources_before != sources_after or template_sha != sha(args.template.read_bytes()):
        raise ValueError('build inputs changed during compilation; discard candidate')
    report=dict(format=1,purpose=('Physical XNU bootstrap for existing iOS system slice' if ios_slice else
                                'Temporary physical XNU diagnostic, not full iOS userspace'),
        kernel_sha256=sha(original_kernel),diagnostic_sha256=sha(original_diagnostic),
        root_payload=dict(root_info,sha256=sha(original_diagnostic)),ios_system_slice=ios_slice,
        template_sha256=template_sha,source_sha256=sources_before,source_inputs_stable=True,
        tool_sha256={name:sha((args.llvm/name).read_bytes()) for name in ('clang','ld.lld','llvm-objcopy')},
        blob_sha256={name:sha(data) for name,data in blobs.items()},image_sha256=sha(image_path.read_bytes()),
        image_bytes=image_path.stat().st_size,commands=commands,layout=constants,segments=segments,
        chained_rebases=rebases,boot_command_line=command,physical_hardware_tested=False,
        verified_framebuffer_boot_override='serial=0 retains video console through PID1',
        vm_page_size=16384,hardware_page_size=4096,unconditional_native_peripheral_ownership=False,
        requested_cpu_count=args.cpus,requested_cpu_mpids=expected_mpids,
        secondary_cpu_start_requires_live_topology=args.cpus>1,
        physical_secondary_cpu_start_proven=False,
        conditional_native_grants=(['display','brightness'] if args.native_display else [])+
            (['i2c0-touch-operability-probe'] if args.native_touch_probe else [])+
            (['pwrap-read-only-probe'] if args.native_pwrap_probe else [])+
            (['msdc-inherited-read-only-probe'] if args.native_msdc_probe else [])+
            (['power-volume-read-only-probe'] if args.native_buttons_probe else [])+
            (['i2c5-inherited-setup-only-probe'] if args.native_charger_setup_probe else [])+
            (['i2c5-inherited-six-PSC-reads'] if args.native_charger_readonly_probe else [])+
            (['watchdog-refresh'] if args.refresh_watchdog else []),
        native_display_requested=args.native_display,brightness_pulse_requested=args.brightness_pulse,
        passive_peripheral_probe=args.probe_peripherals,
        expand_memory_requested=args.expand_memory,
        native_touch_probe_requested=args.native_touch_probe,watchdog_refresh_requested=args.refresh_watchdog,
        watchdog_trial_seconds=args.trial_seconds,watchdog_trial_reset_guaranteed=False,
        native_pwrap_probe_requested=args.native_pwrap_probe,
        native_msdc_probe_requested=args.native_msdc_probe,
        native_msdc_software_timeout_us=PHYSICAL_MSDC_TIMEOUT_US if args.native_msdc_probe else None,
        native_buttons_probe_requested=args.native_buttons_probe,
        native_charger_setup_probe_requested=args.native_charger_setup_probe,
        native_charger_readonly_probe_requested=args.native_charger_readonly_probe,
        charger_transactions_granted=False,charger_control_granted=False,
        conditional_charger_read_transaction_limit=6 if args.native_charger_readonly_probe else 0,
        peripheral_trace=dict(offset=peripheral_record.OFFSET,physical_address=peripheral_record.ADDRESS,
            size=peripheral_record.SIZE,initialized_sha256=sha(peripheral_record.initialized(trace_identity)),
            register_writes=False,native_ownership=False),
        native_handoff='runtime display/PWM admission required' if args.native_display else 'absent',
        watchdog_modified=args.refresh_watchdog,watchdog_reconfigured=False,storage_writes=False,usb_adb_available=False,
        trace=dict(identity=trace_identity.hex(), offset=trace_record.OFFSET,
                   physical_address=trace_record.ADDRESS, size=trace_record.SIZE,
                   initialized_sha256=sha(trace_record.initialized(trace_identity)),
                   physical_retention_proven=False, final_marker_proves_xnu_entry=False),
        framebuffer='Conditional strict live scanout admission; otherwise no display writes',
        display_trace=dict(offset=display_record.OFFSET, physical_address=display_record.ADDRESS,
            size=display_record.SIZE, initialized_sha256=sha(display_record.initialized(trace_identity)),
            register_writes=False, physical_retention_proven=False),
        pwm_trace=dict(offset=pwm_record.OFFSET, physical_address=pwm_record.ADDRESS,
            size=pwm_record.SIZE, initialized_sha256=sha(pwm_record.initialized(trace_identity)),
            register_writes=False, native_ownership=False),
        limitations=['Physical iOS GUI, charging, touch and buttons require runtime acceptance.',
                     'Stock AP watchdog policy remains; exact reset timing/routing is unverified.',
                     'FDT and processor-state mismatch halt before XNU; no guessed RAM fallback.'])
    (out/'physical-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(image=str(image_path),bytes=report['image_bytes'],sha256=report['image_sha256'])))


if __name__ == '__main__':
    main()
