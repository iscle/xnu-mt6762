#!/usr/bin/env python3
"""Bounded offline NTC initialization audit for the supplied artifacts.

Requires Capstone and pyelftools. Never accesses hardware or interprets unique
OTP contents. Output contains selected initialization code and public constants,
not firmware binaries. This audit does not admit calibrated temperature.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_ARCH_ARM64, CS_MODE_THUMB
from elftools.elf.elffile import ELFFile

PRELOADER_SHA = '7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674'
ELF_SHA = '643474799f7c300f2d3c7f5130f697ee359929f13db0750f4dd7b9d648af14fc'
IMAGE_SHA = '82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
FUNCTIONS = ('mt635x_auxadc_probe', 'auxadc_reset',
             'mt6359_efuse_probe', 'mt6359_efuse_read')
PL_RANGES = (('pmic_config_interface', 0x22470c, 0x22475a),
             ('pmic_init', 0x224d58, 0x224dc2),
             ('pmic_init_setting', 0x224f80, 0x22500e),
             ('pmic_init_callsite', 0x223c62, 0x223c66),
             ('pmic_init_setting_callsite', 0x223dcc, 0x223dd0))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(image_path, pl_path, elf_path, output, bsp=None):
    image, pl, elfbytes = (p.read_bytes() for p in (image_path, pl_path, elf_path))
    for name, data, expected in [('Image', image, IMAGE_SHA),
                                 ('preloader', pl, PRELOADER_SHA),
                                 ('stock ELF', elfbytes, ELF_SHA)]:
        if digest(data) != expected:
            raise ValueError(f'{name}: unexpected artifact digest')
    # GFH_FILE_INFO at eMMC boot-region offset0x800; layout from supplied gfh.h.
    magic, size, kind = struct.unpack_from('<IHH', pl, 0x800)
    if (magic & 0xffffff, size, kind, pl[0x808:0x814]) != (
            0x4d4d4d, 56, 0, b'FILE_INFO\0\0\0'):
        raise ValueError('unexpected GFH_FILE_INFO')
    load, file_len, max_size, content, sig_len, jump, attr = struct.unpack_from('<7I', pl, 0x81c)
    if (load, content, jump) != (0x200f10, 0xf0, 0xf0):
        raise ValueError('unexpected preloader load geometry')
    delta = load - 0x800
    text, ranges = [], []
    thumb = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    for name, start, end in PL_RANGES:
        blob = pl[start-delta:end-delta]
        ranges.append(dict(name=name, start=hex(start), end=hex(end),
                           file_offset=hex(start-delta), sha256=digest(blob)))
        text.append(f'\npreloader {name} {start:#x}..{end:#x}')
        text.extend(f'{d.address:#x}: {d.mnemonic} {d.op_str}'
                    for d in thumb.disasm(blob, start))
    # Exact PC-relative LDR in pmic_init loads this literal, then BLX printf.
    string_pointer = struct.unpack_from('<I', pl, 0x246c0)[0]
    string_offset = string_pointer - delta
    if pl[string_offset:].split(b'\0', 1)[0] != b'No EFUSE SW Load\n':
        raise ValueError('unexpected disabled-load diagnostic')
    table = [struct.unpack_from('<4H', pl, 0x37f00 + i*8) for i in range(131)]
    selected = [dict(file_offset=hex(0x37f00+i*8), address=hex(a), value=hex(v),
                     mask=hex(m), shift=s) for i, (a,v,m,s) in enumerate(table)
                if 0x1000 <= a <= 0x1216]
    coefficient_addresses = {0x10de,0x10e0,0x11a2,0x11a4,0x11a6,0x11a8,0x11aa,0x11ac}
    if any(a in coefficient_addresses for a,_,_,_ in table):
        raise ValueError('unexpected coefficient write in selected initialization table')
    stock_ranges = []
    with elf_path.open('rb') as file:
        elf = ELFFile(file)
        symbols = sorted((s['st_value'],s.name) for s in elf.get_section_by_name('.symtab').iter_symbols() if s['st_value'])
        names = dict((name,address) for address,name in symbols)
        for name in FUNCTIONS:
            start = names[name]
            end = min(address for address,_ in symbols if address > start)
            if end-start > 8192:
                raise ValueError('unexpected inferred symbol extent')
            segment = next(s for s in elf.iter_segments() if s['p_vaddr'] <= start and end <= s['p_vaddr']+s['p_filesz'])
            file.seek(segment['p_offset'] + start-segment['p_vaddr'])
            blob = file.read(end-start)
            stock_ranges.append(dict(name=name,start=hex(start),end=hex(end),sha256=digest(blob),range_method='next distinct original symbol'))
            text.append(f'\nstock {name} {start:#x}..{end:#x}')
            for d in Cs(CS_ARCH_ARM64, 0).disasm(blob,start):
                line = f'{d.address:#x}: {d.mnemonic} {d.op_str}'
                if d.mnemonic == 'bl':
                    target = int(d.op_str[1:],16)
                    line += ' ' + next((n for a,n in symbols if a == target),'')
                text.append(line)
    base = 0xffffff8008080000
    ptr = struct.unpack_from('<Q', image, 0xffffff8009105df0-base+0x48)[0]
    count = struct.unpack_from('<I', image, 0xffffff8009105df0-base+0x50)[0]
    if (ptr,count) != (0xffffff8009106010,4):
        raise ValueError('unexpected AUXADC reset table')
    reset = [dict(address=hex(a),mask=hex(m),value=hex(v))
             for a,m,v in (struct.unpack_from('<III',image,ptr-base+i*12) for i in range(count))]
    result = dict(image_sha256=IMAGE_SHA, preloader_sha256=PRELOADER_SHA,
                  stock_elf_sha256=ELF_SHA, calibrated_temperature_admitted=False,
                  physical_device_access=False,
                  gfh=dict(offset='0x800',load_address=hex(load),content_offset=hex(content),entry=hex(load+jump),va_minus_file_offset=hex(delta)),
                  preloader_functions=ranges, stock_functions=stock_ranges,
                  disabled_efuse_copy=dict(load_instruction='0x224d72',print_call='0x224d74',literal_file_offset='0x246c0',string_file_offset=hex(string_offset),text='No EFUSE SW Load'),
                  initialization_table=dict(file_offset='0x37f00',record_count=131,record_size=8,auxadc_related_records=selected,coefficient_writes_found=False,write_results_verified_by_loop=False),
                  stock_reset_table=reset,
                  limitations=['Static control flow is not a record of a successful physical boot.',
                               'No proof of hardware shadow autoload, trim bank mapping, compensation polarity, or calibrated channel transfer.',
                               'The selected routines do not establish absence of every possible unrelated firmware writer.'])
    if bsp is not None:
        prefix = 'vendor/mediatek/proprietary/bootable/bootloader/preloader/platform/'
        paths = [prefix+'common/inc/gfh.h',
                 *(prefix+'mt6765/src/drivers/'+name for name in
                   ('pmic.c','pmic_efuse.c','pmic_initial_setting.c')),
                 'kernel-4.14/drivers/iio/adc/mt635x-auxadc.c',
                 'kernel-4.14/drivers/misc/mediatek/pmic/mt6357/v1/pmic_auxadc.c',
                 'kernel-4.14/include/linux/mfd/mt6357/registers.h']
        sources = {path:(bsp/path).read_bytes() for path in paths}
        settings = sources[paths[3]].decode().split('struct pmic_setting init_setting[] = {',1)[1].split('};',1)[0]
        rows = [tuple(int(x,0) for x in row) for row in re.findall(
            r'\{(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),\s*(\d+)\}', settings)]
        result['reference_bsp'] = dict(
            sources=[dict(path=path,sha256=digest(data)) for path,data in sources.items()],
            setting_record_count=len(rows),
            initial_table_exactly_matches_artifact=rows == table,
            scope='Table byte match corroborates this table only, not identity of every driver path.')
    output.mkdir(parents=True,exist_ok=False)
    (output/'ntc-init-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'ntc-init-disassembly.txt').write_text('\n'.join(line.rstrip() for line in text)+'\n')
    print('Verified exact artifact hashes; extracted five Thumb ranges, four stock functions, and bounded ADC tables. Calibration remains inadmissible.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--preloader',type=Path,required=True)
    parser.add_argument('--stock-elf',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bsp',type=Path)
    args=parser.parse_args()
    run(args.image,args.preloader,args.stock_elf,args.output,args.bsp)
