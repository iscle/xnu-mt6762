#!/usr/bin/env python3
"""Read-only, hash-pinned LK confirmation/key audit; no device access.

Requires Capstone. Output contains selected decoded instructions and keypad
properties only, never binary payloads, command serials, FRP or key material.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

LK_SHA = '5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
RANGES = [('unlock_prompt',0x480260fc,0x48026166),
          ('unlock_confirmation',0x4802636c,0x480264a8),
          ('key_detect',0x48004aec,0x48004b66),
          ('key_dt_loader',0x4800493c,0x48004a9e),
          ('pmic_power_detect',0x48007848,0x48007884),
          ('pmic_home_detect',0x4800788c,0x480078c8)]
KEYS = {'mediatek,kpd-hw-pwrkey','mediatek,kpd-hw-rstkey',
        'mediatek,kpd-hw-recovery-key','mediatek,kpd-hw-factory-key',
        'mediatek,kpd-hw-init-map'}
def sha(b): return hashlib.sha256(b).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dump',type=Path,required=True)
    p.add_argument('--firmware',type=Path,required=True)
    p.add_argument('--bsp',type=Path,required=True)
    p.add_argument('--trial',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); lk=(a.dump/'lk.bin').read_bytes()
    if sha(lk)!=LK_SHA: raise ValueError('Unexpected LK artifact')
    extractor=Path(__file__).resolve().parents[1]/'firmware/extract.py'
    spec=importlib.util.spec_from_file_location('fdt_extract',extractor)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    off=0xad850; size=struct.unpack_from('>I',lk,off+4)[0]
    embedded=lk[off:off+size]
    if embedded!=(a.firmware/'boot.bin.dtb').read_bytes():
        raise ValueError('Unexpected embedded/base DT relation')
    dt=[]
    for name,blob in [('lk_embedded',embedded),('dtbo', (a.firmware/'dtbo.bin.dtb').read_bytes())]:
        props=[]
        for node,fields in m.fdt_properties(blob).items():
            for key,value in fields.items():
                if key in KEYS:
                    props.append({'node':node,'property':key,'cells':list(struct.unpack('>'+'I'*(len(value)//4),value))})
        dt.append({'name':name,'sha256':sha(blob),'size':len(blob),'selected_properties':props})
    ranges=[];delta=0x47fffe00
    for name,start,end in RANGES:
        blob=lk[start-delta:end-delta]
        ins=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(blob,start))
        if sum(i.size for i in ins)!=len(blob):raise ValueError('Incomplete range decoding: '+name)
        ranges.append({'name':name,'va':hex(start),'end':hex(end),'file_offset':hex(start-delta),'sha256':sha(blob),'instructions':[{'va':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in ins]})
    prefix='vendor/mediatek/proprietary/bootable/bootloader/lk/'
    sources=[prefix+s for s in ['app/mt_boot/sec_unlock.c','app/mt_boot/fastboot.c','platform/mt6765/mtk_key.c','target/k62v1_64_bsp/include/target/cust_key.h']]
    trial=[]
    if a.trial:
        for name in ('flashing-unlock','unlock-state-after-request','unlock-ability'):
            raw=(a.trial/(name+'.json')).read_bytes();j=json.loads(raw)
            trial.append({'file':name+'.json','sha256':sha(raw),'returncode':j['returncode'],'output':j['output']})
    out={'authority':'Exact dumped LK and DT, selected BSP cross-check; no live key-register observation.',
         'lk_sha256':LK_SHA,'code_ranges':ranges,'device_trees':dt,
         'source_files':[{'path':s,'sha256':sha((a.bsp/s).read_bytes())} for s in sources],
         'sanitized_trial_results':trial,
         'findings':{'confirmation_hardware_key':17,'confirmation_va':'0x48026398','cancel_key_source':'key DT struct +0x13c (factory), default0',
                     'key17_route':'hardware reset/home17 in DTBO and fallback; PMIC register0x24 bit3 active low',
                     'power_route':'hardware key8, PMIC register0x24 bit1 active low',
                     'volume_keypad_map':'DTBO index0 Linux114, index1 Linux115',
                     'poll_timeout_present':False,'cancel_returns_fastboot_okay':True,'cancel_delay_ms':3000,
                     'permission_checked_after_confirmation':True},
         'limits':['No proof of physical key reaching PMIC HOME/reset input.',
                   'Android input events do not prove LK confirmation key routing.',
                   'Historical OKAY without Start unlock flow is consistent with cancel; exact physical action is unobserved.',
                   'OEM unlock ability and confirmation key mismatch are independent barriers.',
                   'No alternate unlock commands, patches or bypass attempted.']}
    a.output.write_text(json.dumps(out,indent=2)+'\n')
    print(f'{len(ranges)} fully decoded LK ranges; keypad-only DT evidence; no phone access')
if __name__=='__main__':main()
