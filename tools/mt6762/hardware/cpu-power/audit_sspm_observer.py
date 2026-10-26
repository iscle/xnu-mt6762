#!/usr/bin/env python3
"""Pin passive SSPM observation evidence and replay the stock AP guard writer.

Offline only. Original AArch64 instructions execute with modeled memory copy,
zeroing and ftrace callbacks; no peripheral or SSPM firmware is emulated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_SP, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X30

BASE = 0xffffff8008080000
IMAGE_SHA = '82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
ELF_SHA = '643474799f7c300f2d3c7f5130f697ee359929f13db0750f4dd7b9d648af14fc'
SPANS = {
    'init_cpuhvfs_debug_repo': (0xffffff8009619f00, 0xffffff8009619f78),
    'cpuhvfs_pvt_tbl_create': (0xffffff8009619b24, 0xffffff8009619dd0),
    'cpuhvfs_get_cur_dvfs_freq_idx': (0xffffff800867b230, 0xffffff800867b268),
    'cpuhvfs_get_volt': (0xffffff800867b304, 0xffffff800867b33c),
    'cpuhvfs_set_cluster_load_freq': (0xffffff800867b4f8, 0xffffff800867b5dc),
    'sspm_mbox_read': (0xffffff80088095b0, 0xffffff8008809614),
    'sspm_mbox_polling': (0xffffff8008809678, 0xffffff8008809760),
    'sspm_mbox_irq_handler': (0xffffff8008809b54, 0xffffff8008809bdc),
}
SOURCES = [
    'kernel-4.14/drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c',
    'kernel-4.14/drivers/misc/mediatek/sspm/v1/sspm_mbox.c',
    'vendor/mediatek/proprietary/bootable/bootloader/preloader/platform/mt6765/src/core/main.c',
]


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def replay_guard_writer(image):
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    mapped = set()
    def page(address):
        address &= ~4095
        if address in mapped:
            return
        u.mem_map(address, 4096)
        mapped.add(address)
        offset = address-BASE
        if 0 <= offset < len(image):
            u.mem_write(address, image[offset:offset+4096])
    callbacks = {0xffffff800809ef9c: 'ftrace_noop',
                 0xffffff800809316c: 'memcpy_fromio_model',
                 0xffffff800809328c: 'memset_io_model'}
    for address in [SPANS['init_cpuhvfs_debug_repo'][0], *callbacks,
                    0xffffff80099cc000, 0xffffff80099cd000]:
        page(address)
    for address in range(0x60000000, 0x60010000, 4096):
        page(address)
    initial = bytes([0x6d])*0x1400
    u.mem_write(0x60000000, initial)
    u.mem_write(0xffffff80099cc008, struct.pack('<Q', 0x60000000))
    calls = []
    def dispatch(uc, address, size, data):
        if address not in callbacks:
            return
        calls.append(callbacks[address])
        dst, src, size = [uc.reg_read(reg) for reg in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2)]
        if address == 0xffffff800809316c:
            assert (dst, src, size) == (0xffffff80099cc044, 0x60000000, 0x1400)
            uc.mem_write(dst, bytes(uc.mem_read(src, size)))
        elif address == 0xffffff800809328c:
            assert (dst, src, size) == (0x600002a0, 0, 0x1160)
            uc.mem_write(dst, bytes(size))
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))
    u.hook_add(UC_HOOK_CODE, dispatch)
    u.reg_write(UC_ARM64_REG_SP, 0x6000e000)
    u.reg_write(UC_ARM64_REG_X30, 0x6000f000)
    u.emu_start(SPANS['init_cpuhvfs_debug_repo'][0], 0x6000f000, count=1000)
    assert u.reg_read(UC_ARM64_REG_PC) == 0x6000f000
    result = bytes(u.mem_read(0x60000000, 0x1400))
    guards = [struct.unpack_from('<I', result, offset)[0] for offset in (0, 4, 8, 12, 0x2a0)]
    assert guards == [0x55aa55aa, 0xaa55aa55, 0x55aa55aa, 0xaa55aa55, 0x55aa55aa]
    assert result[0x10:0x250] == initial[0x10:0x250]
    assert struct.unpack_from('<2I', result, 0x320) == (15, 15)
    assert struct.unpack_from('<3I', result, 0x300) == (0, 0, 0)
    assert struct.unpack_from('<3I', result, 0x354) == (0, 0, 0)
    assert struct.unpack_from('<3I', result, 0x3a4) == (0, 0, 0)
    assert bytes(u.mem_read(0xffffff80099cc044, 0x1400)) == initial
    assert calls == list(callbacks.values())
    return {'passed': True, 'guards_written_by_ap': [hex(v) for v in guards],
            'ppm_defaults': [15, 15], 'eem_current_index_vote_words_zero': True,
            'pvt_region_unchanged': True, 'old_repository_backed_up': True,
            'modeled_callbacks': {hex(k): v for k, v in callbacks.items()},
            'cpu_ipi_or_firmware_execution': False,
            'scope': 'Exact AP initializer only; RAM and three callbacks modeled, no physical state.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('image', 'elf', 'bsp', 'capture_root', 'output'):
        parser.add_argument('--'+name.replace('_', '-'), required=True, type=Path)
    args = parser.parse_args()
    image = args.image.read_bytes()
    if sha(image) != IMAGE_SHA or sha(args.elf.read_bytes()) != ELF_SHA:
        parser.error('Exact audited Image and ELF digests required')
    with args.elf.open('rb') as source:
        symbols = {s.name: s['st_value'] for s in ELFFile(source).get_section_by_name('.symtab').iter_symbols()}
    assert all(symbols[name] == lo for name, (lo, _) in SPANS.items())
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    spans, assembly = [], []
    for name, (lo, hi) in SPANS.items():
        data = image[lo-BASE:hi-BASE]
        spans.append({'name': name, 'start': hex(lo), 'end_exclusive': hex(hi), 'sha256': sha(data)})
        assembly.append(name)
        assembly.extend(f'{ins.address:016x} {ins.mnemonic} {ins.op_str}' for ins in md.disasm(data, lo))
    captures = []
    for n in (26, 27):
        path = args.capture_root/f'capture{n}'/'peripherals-result.json'
        blob = path.read_bytes()
        registers = json.loads(blob)['registers']
        count = sum(0x110c00 <= int(r['address'], 16) < 0x112000 or
                    0x10440000 <= int(r['address'], 16) < 0x10480000 for r in registers)
        captures.append({'capture': n, 'peripherals_json_sha256': sha(blob),
                         'register_count': len(registers), 'sspm_csram_registers_present': count})
    evidence = {'image_sha256': IMAGE_SHA, 'elf_sha256': ELF_SHA, 'spans': spans,
                'bsp_sources': [{'path': p, 'sha256': sha((args.bsp/p).read_bytes())} for p in SOURCES],
                'execution': replay_guard_writer(image), 'capture_coverage': captures,
                'limits': ['Captures26/27 do not observe SSPM registers/CSRAM or establish firmware preservation.',
                           'Guard/table representation, empty pins and disabled IRQ do not grant ownership or initialization.',
                           'The observer remains opt-in and has not executed on the physical phone.']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'sspm-observer-evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
    (args.output/'sspm-observer-disassembly.txt').write_text('\n'.join(assembly)+'\n')
    print(json.dumps({'passed': True, 'stock_guard_writer_replayed': True, 'spans': len(spans)}))


if __name__ == '__main__':
    main()
