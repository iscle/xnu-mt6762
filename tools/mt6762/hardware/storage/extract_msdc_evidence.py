#!/usr/bin/env python3
"""Bounded offline MSDC evidence. Never opens a device or writes source inputs.
Requires pyelftools + capstone. Records controller code and technical boot-mode
records only; excludes card identity, partition contents and crypto key ranges.
"""
import argparse, hashlib, json, re
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

FUNCTIONS = ('msdc_command_start', 'msdc_command_resp_polling', 'msdc_pio_read',
             'msdc_dma_start', 'msdc_dma_stop', 'msdc_dma_setup', 'msdc_init_hw',
             'msdc_set_mclk', 'msdc_set_pin_mode', 'msdc_emmc_power',
             'msdc_get_ccf_clk_pointer', 'msdc_complete_mqr_crypto',
             'mtk_pll_recalc_rate', '__mtk_pll_recalc_rate')
LOG_PATTERN = re.compile(r'(?:\[SD0\] (?:SET_CLK\([^\r\n]{0,140}|Size: [0-9]+ MB, Max.Speed: [0-9]+ kHz, blklen\([0-9]+\), nblks\([0-9]+\)|Initialized, eMMC[0-9]+)|msdc0 -> !!! Set<[^\r\n]{0,150}|mmc0: new HS400 MMC card at address [0-9A-Fa-f]{4})')

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-elf', type=Path, required=True)
    parser.add_argument('--expdb', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    log = args.expdb.read_bytes()
    records = []
    for span in re.finditer(rb'[\x20-\x7e\t]{8,500}', log):
        for found in LOG_PATTERN.finditer(span.group().decode('ascii')):
            records.append({'offset': hex(span.start() + found.start()), 'text': found.group()})
    ranges, assembly = [], []
    with args.stock_elf.open('rb') as file:
        elf = ELFFile(file)
        if elf['e_machine'] != 'EM_AARCH64':
            raise ValueError('expected original AArch64 stock kernel ELF')
        symbols = sorted((s['st_value'], s.name) for s in elf.get_section_by_name('.symtab').iter_symbols() if s['st_value'])
        decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        for name in FUNCTIONS:
            matches = [(i, addr) for i, (addr, symbol) in enumerate(symbols) if symbol == name]
            if len(matches) != 1:
                raise ValueError(f'{name}: expected one exact symbol')
            index, start = matches[0]
            end = next(addr for addr, _ in symbols[index + 1:] if addr > start)
            if end - start > 16384:
                raise ValueError(f'{name}: unexpectedly large inferred function range')
            blocks = [segment for segment in elf.iter_segments() if segment['p_vaddr'] <= start and end <= segment['p_vaddr'] + segment['p_filesz']]
            if len(blocks) != 1:
                raise ValueError(f'{name}: ambiguous load mapping')
            segment = blocks[0]
            file.seek(segment['p_offset'] + start - segment['p_vaddr'])
            data = file.read(end - start)
            ranges.append({'name': name, 'start': hex(start), 'end': hex(end), 'sha256': hashlib.sha256(data).hexdigest(), 'range_method': 'next distinct original ELF symbol'})
            assembly.append(f'\n{name} {start:#x}..{end:#x}')
            assembly.extend(f'{d.address:#x}: {d.mnemonic} {d.op_str}' for d in decoder.disasm(data, start))
    evidence = {'stock_elf_sha256': digest(args.stock_elf), 'expdb_sha256': hashlib.sha256(log).hexdigest(), 'function_ranges': ranges, 'historical_boot_records': records, 'limitations': ['Retained historical logs are not current register readback.', 'Function end inferred from next symbol; exact named functions only.', 'No device execution, storage read or register access performed.']}
    (args.output / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (args.output / 'stock-functions.txt').write_text('\n'.join(assembly) + '\n')
    print(f'{len(ranges)} functions, {len(records)} narrowly selected historical records')

if __name__ == '__main__':
    main()
