#!/usr/bin/env python3
"""Bounded read-only LK handoff evidence; no phone access or payload generation.

Requires Capstone. Extracts only code ranges and allowlisted technical boot-log
lines; excludes command lines, device identifiers, partition UUIDs and secrets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

LK_SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
EXPDB_SHA='6675a9ae0eead546971136c2244be082a137f8b0b17ee5b5d5bc0ba98fce5f86'
BOOT_SHA='95f362d6c5e018fb588ce1101a75120157079571e8749e349141a5a906f09296'
RANGES=[('videolfb_payload_writer',0x4800402c,0x480040be,CS_MODE_THUMB),
        ('lk_jump64_wrapper',0x4801a03c,0x4801a064,CS_MODE_THUMB),
        ('final_cache_mmu_cleanup_calls',0x4801bb00,0x4801bb2a,CS_MODE_THUMB),
        ('final_watchdog_calls',0x4801bbc6,0x4801bbd4,CS_MODE_THUMB),
        ('final_kernel64_arguments',0x4801bc32,0x4801bc44,CS_MODE_THUMB),
        ('cache_disable',0x48016a80,0x48016adc,CS_MODE_ARM),
        ('mmu_disable',0x48017564,0x48017576,CS_MODE_THUMB),
        ('sctlr_read_write',0x48016d3c,0x48016d4c,CS_MODE_ARM),
        ('platform_uninit_tailcall',0x48002ca4,0x48002ca8,CS_MODE_THUMB),
        ('interrupt_deinit',0x48026b44,0x48026bc6,CS_MODE_THUMB),
        ('kernel_smc_setup',0x48026674,0x4802669e,CS_MODE_THUMB),
        ('smc_trampoline',0x48026654,0x48026672,CS_MODE_THUMB),
        ('watchdog_length',0x48042f50,0x48042f68,CS_MODE_THUMB),
        ('watchdog_restart',0x48042f6c,0x48042f7c,CS_MODE_THUMB)]
# Patterns deliberately exclude the general SSPM/PMIC/command-line inventory.
PATTERNS=[
 rb'mblock_reserve-R\[[0-9]+\]\.start: 0x[0-9a-fA-F]+, size: 0x[0-9a-fA-F]+ map:[01] name:[A-Za-z0-9_-]+',
 rb'mblock_reserve-R start: 0x[0-9a-fA-F]+, sz: 0x[0-9a-fA-F]+ map:[01] name:(?:kernel_addr_mb|dtb_kernel_addr_mb|ramdisk_addr_mb)',
 rb'total_dram_size: 0x[0-9a-fA-F]+, max_dram_size: 0x[0-9a-fA-F]+',
 rb'boot linux-64 via EL2, pc=0x[0-9a-fA-F]+, x0=0x[0-9a-fA-F]+, x1=0x[0-9a-fA-F]+, mode=0x[0-9a-fA-F]+',
 rb'\[LK\]jump to K64 0x[0-9a-fA-F]+',
 rb'videolfb - (?:fb_base +|islcmfound |fps +|vram +|lcmname +)= [A-Za-z0-9_x]+',
 rb'PWRAP\] (?:pwrap_init_lk|is_pwrap_init_done 1|\[PMIC_WRAP\] pwrap_init already init, do nothing)',
 rb'WDT\] +mtk_wdt_mode_config LK +mode value=[0-9a-fA-F]+, tmp:[0-9a-fA-F]+',
 rb'SSPM: set reserved mem status=okay',
]


def sha(b):return hashlib.sha256(b).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dump',type=Path,required=True)
    p.add_argument('--bsp',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();lk=(a.dump/'lk.bin').read_bytes();lk2=(a.dump/'lk2.bin').read_bytes()
    boot=(a.dump/'boot.bin').read_bytes();exp=(a.dump/'expdb.bin').read_bytes()
    if sha(lk)!=LK_SHA or lk2!=lk or sha(boot)!=BOOT_SHA or sha(exp)!=EXPDB_SHA:
        raise ValueError('unexpected exact-artifact identity')
    if struct.unpack_from('<I',lk,0x274)[0]!=0x48000000:
        raise ValueError('unexpected LK startup load-base literal')
    records=[];delta=0x48000000-0x200
    for name,start,end,mode in RANGES:
        blob=lk[start-delta:end-delta]
        records.append(dict(name=name,va=hex(start),end=hex(end),file_offset=hex(start-delta),sha256=sha(blob),mode='ARM' if mode==CS_MODE_ARM else 'Thumb',instructions=[dict(va=hex(i.address),instruction=i.mnemonic+' '+i.op_str) for i in Cs(CS_ARCH_ARM,mode).disasm(blob,start)]))
    lines=[]
    for pattern in PATTERNS:
        for m in re.finditer(pattern,exp):
            lines.append(dict(file_offset=hex(m.start()),text=m.group().decode('ascii')))
    lines.sort(key=lambda r:int(r['file_offset'],16))
    prefix='vendor/mediatek/proprietary/bootable/bootloader/lk/'
    paths=[prefix+'app/mt_boot/mt_boot.c',prefix+'app/mt_boot/sys_commands.c']
    paths += [prefix+'platform/mt6765/'+name for name in ('atags.c','mt_disp_drv.c','platform.c','mt_sspm.c','mtk_wdt.c','rules.mk','include/platform/mtk_wdt.h','include/platform/ddp_data_type.h','ddp_ovl.c')]
    paths += ['vendor/mediatek/proprietary/trustzone/atf/v1.4/plat/mediatek/mt6765/bl31_plat_setup.c']
    result=dict(authority='Exact LK code and retained historical boot logs; selected BSP cross-check. No physical execution/readback.',
                artifacts=dict(lk_sha256=LK_SHA,lk2_identical=True,boot_sha256=BOOT_SHA,expdb_sha256=EXPDB_SHA),
                lk=dict(partition_header_size=512,load_base='0x48000000',base_literal_file_offset='0x274',bounded_ranges=records),
                selected_historical_records=lines,
                source_files=[dict(path=name,sha256=sha((a.bsp/name).read_bytes())) for name in paths],
                video_tag=dict(endian='little',header_present=False,fields={'fb_base':[0,8],'islcmfound':[8,4],'fps':[12,4],'vram':[16,4],'lcmname':[20,'NUL-terminated']},absent_fields=['width','height','stride','pixel_format','active_layer','rotation','DMA_translation']),
                caveats=['Historical normal boot is not proof of a future fastboot entry state.', 'GZ historical mode0x3c5 is EL1h; generic selected ATF source can chooseEL2, so entry must measure CurrentEL.', 'Watchdog length is30seconds; IRQ/dual-stage/reset routing means this is not a proved exact reset deadline.', 'Static512MiB DT memory/reg is not actual6GiB runtime map; preserve all runtime reservations.', 'No lab-fixture/native peripheral ownership is established by this evidence.'])
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(f'{len(records)} bounded LK ranges, {len(lines)} allowlisted historical records; no device access')

if __name__=='__main__':main()
