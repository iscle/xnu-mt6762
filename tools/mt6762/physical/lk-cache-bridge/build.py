#!/usr/bin/env python3
"""Build injectable Thumb blob and guarded patch description, never full LK image.

The requested address is a linker/test coordinate, NOT a verified physical cave.
"""
import argparse,hashlib,json,struct,subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
LK_SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
CALL=0x4801dede
ORIGINAL=bytes.fromhex('19f02bf8')
def bl(source,target):
    delta=target-(source+4)
    if delta&1 or not -(1<<24)<=delta<(1<<24):raise ValueError('Thumb BL target out of range/alignment')
    value=delta & 0x1ffffff;s=(value>>24)&1;i1=(value>>23)&1;i2=(value>>22)&1
    return struct.pack('<HH',0xf000|(s<<10)|((value>>12)&1023),0xd000|((1^i1^s)<<13)|((1^i2^s)<<11)|((value>>1)&2047))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lk',required=True,type=Path)
    p.add_argument('--llvm-bin',required=True,type=Path);p.add_argument('--load-address',required=True,type=lambda x:int(x,0))
    p.add_argument('--out',required=True,type=Path);a=p.parse_args();raw=a.lk.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=LK_SHA or raw[CALL-0x47fffe00:CALL-0x47fffe00+4]!=ORIGINAL:raise ValueError('LK identity/callsite guard failed')
    if a.load_address&3:raise ValueError('Load address must be4-byte aligned')
    patch=bl(CALL,a.load_address);a.out.mkdir(parents=True,exist_ok=True);src=Path(__file__).resolve().parent
    linker=a.out/'bridge.ld';linker.write_text(f'ENTRY(bridge_entry)\nSECTIONS {{ . = 0x{a.load_address:x}; .text : {{ *(.text.entry) *(.text*) *(.rodata*) }} /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }} }}\n')
    elf=a.out/'bridge.elf'
    cmd=[str(a.llvm_bin/'clang'),'--target=arm-none-eabi','-mcpu=cortex-a53','-mthumb','-Os','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-nostdlib','-Wl,--build-id=none','-Wl,-T,'+str(linker),str(src/'entry.S'),str(src/'bridge.c'),'-o',str(elf)]
    subprocess.run(cmd,check=True)
    with elf.open('rb') as f:
        e=ELFFile(f);section=e.get_section_by_name('.text');blob=section.data()
        if section['sh_addr']!=a.load_address:raise ValueError('Unexpected code address')
        if any(s['sh_type']=='SHT_REL' and s['sh_size'] for s in e.iter_sections()):raise ValueError('Unresolved relocation')
    (a.out/'bridge.bin').write_bytes(blob)
    manifest={'deployment_status':'INJECTABLE_BLOB_ONLY_NO_VERIFIED_RAM_PLACEMENT_NO_PHONE_EXECUTION',
        'lk_sha256':LK_SHA,'lk_partition_size':len(raw),'lk_declared_payload_size':struct.unpack_from('<I',raw,4)[0],
        'placement':{'address':hex(a.load_address),'size':len(blob),'physical_ownership_verified':False,'instruction_cache_maintenance_required':True},
        'blob_sha256':hashlib.sha256(blob).hexdigest(),'patch':{'va':hex(CALL),'file_offset':hex(CALL-0x47fffe00),'expected_hex':ORIGINAL.hex(),'replacement_hex':patch.hex()},
        'source_sha256':{n:hashlib.sha256((src/n).read_bytes()).hexdigest() for n in ('bridge.c','entry.S','build.py')},
        'limits':['No flashable/patched LK file generated.','No append/cave load-extent proof.','Models do not prove physical execution or later XNU handoff.']}
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(f'{len(blob)} bytes; guarded BL patch; placement remains unverified')
if __name__=='__main__':main()
