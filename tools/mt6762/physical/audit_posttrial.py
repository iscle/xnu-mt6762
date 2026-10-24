#!/usr/bin/env python3
"""Offline bounded trial audit: selected boot failures and public state metadata.

No device access, no partition writes, no complete private logs or persistent
value bytes in output. Requires Capstone; hash pins identify this exact capture.
"""
import argparse, hashlib, json, re, struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
LK_SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
EXP_SHA='febda44f4e7455617a127617c6bc4013dd13e4027f16e558416247a977de6cbc'
RANGES=[('fastboot_caller',0x4801deb4,0x4801dee2),
        ('decapsulator_entry_ignores_argument',0x48036f38,0x48036f66),
        ('decapsulator_null_branch',0x48037270,0x48037282),
        ('decapsulator_panic',0x480371bc,0x480371c6),
        ('cached_image_lookup',0x48037d24,0x48037d30)]
PATTERNS=[rb'\[[0-9]+\] \[fastboot: command buf\]-\[boot\]-\[len=4\]',
 rb'\[[0-9]+\] \[fastboot\]-\[download_base:0x[0-9a-f]+\]-\[download_size:0x[0-9a-f]+\]',
 rb'\[[0-9]+\] boot image is NULL',
 rb'\[[0-9]+\] panic \(caller 0x[0-9a-f]+\): boot image decapsulate fail!',
 rb'rst from: lk',rb'kedump: boot_reason\([0-9]+\)',
 rb'RAM_CONSOLE\. wdt_status 0x[0-9a-f]+, fiq_step 0x[0-9a-f]+, exp_type 0x[0-9a-f]+',
 rb'RAM_CONSOLE detect abnormal boot exp_type:0x[0-9a-f]+',
 rb'\[LK\]jump to K64 0x[0-9a-f]+',
 rb'boot linux-64 via EL2, pc=0x[0-9a-f]+, x0=0x[0-9a-f]+, x1=0x[0-9a-f]+, mode=0x[0-9a-f]+']
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--trial',required=True,type=Path);p.add_argument('--dump',required=True,type=Path)
 p.add_argument('--bsp',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
 a=p.parse_args();files={}
 for name in ['seccfg-after.bin','seccfg-posttrial.bin','expdb-posttrial.bin','expdb-posttrial-complete.bin']:
  files[name]=(a.trial/name).read_bytes()
 exp=files['expdb-posttrial-complete.bin'];lk=(a.dump/'lk.bin').read_bytes()
 if sha(lk)!=LK_SHA or sha(exp)!=EXP_SHA:raise ValueError('Unexpected artifact hash')
 before=files['seccfg-after.bin'];after=files['seccfg-posttrial.bin']
 if len(before)!=len(after):raise ValueError('Unequal seccfg capture lengths')
 diffs=[i for i,(x,y) in enumerate(zip(before,after)) if x!=y]
 magic,keylen,valuelen=struct.unpack_from('>III',after,0x240)
 key=after[0x24c:0x24c+keylen]
 if (magic,key,valuelen)!=(0x90790804,b'avb.managed_verity_mode',32):raise ValueError('Unexpected persistent record')
 records=[]
 for pat in PATTERNS:
  for m in re.finditer(pat,exp):records.append({'offset':hex(m.start()),'text':m.group().decode()})
 records.sort(key=lambda x:int(x['offset'],16));ranges=[];delta=0x47fffe00
 for name,start,end in RANGES:
  blob=lk[start-delta:end-delta];ins=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(blob,start))
  if sum(i.size for i in ins)!=len(blob):raise ValueError('Incomplete decoding')
  ranges.append({'name':name,'start':hex(start),'end':hex(end),'sha256':sha(blob),'instructions':[{'va':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in ins]})
 literals=[]
 for load,disp,add,expected in [(0x48036f3e,0x420,0x48036f48,b'vendor_boot'),
                               (0x48036f44,0x41c,0x48036f4a,b'boot'),
                               (0x48037278,0x124,0x4803727a,b'boot image is NULL\n')]:
  pool=((load+4)&~3)+disp
  target=(struct.unpack_from('<I',lk,pool-delta)[0]+add+4)&0xffffffff
  off=target-delta; value=lk[off:lk.index(0,off)]
  if value!=expected:raise ValueError('Unexpected referenced literal')
  literals.append({'load_va':hex(load),'add_pc_va':hex(add),'pool_va':hex(pool),'target_va':hex(target),'text':value.decode()})
 prefix='vendor/mediatek/proprietary/bootable/bootloader/lk/'
 paths=[prefix+x for x in ['app/mt_boot/sys_commands.c','platform/common/boot/boot_info.c','platform/common/boot/avb20/load_vfy_boot.c','platform/common/boot/avb20/dm_verity.c','platform/common/include/avb_persist.h','platform/common/avb/libavb/avb_slot_verify.c']]
 out={'authority':'Offline exact capture and LK; BSP cross-check. No phone actions.',
      'artifacts':{n:{'size':len(b),'sha256':sha(b)} for n,b in files.items()},'lk_sha256':LK_SHA,
      'seccfg':{'first512_unchanged':before[:512]==after[:512], 'lock_state_before':struct.unpack_from('<I',before,12)[0],'lock_state_after':struct.unpack_from('<I',after,12)[0],
      'changed_byte_count':len(diffs),'first_change':hex(min(diffs)),'last_change':hex(max(diffs)),
      'persistent_descriptor':{'offset':'0x240','magic':hex(magic),'key':key.decode(),'key_size':keylen,'value_size':valuelen,'value_not_published':True}},
      'allowlisted_logs':records,'bounded_code':ranges,'resolved_literals':literals,'source_files':[{'path':s,'sha256':sha((a.bsp/s).read_bytes())} for s in paths],
      'conclusions':['Fastboot attempt with5bf000 bytes panics in LK before XNU entry.',
        'Caller passes download address; shipped callee replaces it with boot/vendor_boot cache lookups; boot lookup NULL triggers observed panic.',
        'Unlock header unchanged; new AVB managed-verity record explains persistent EIO warning per supplied BSP.',
        'Initial cause of dm-verity status is not established by this bounded capture.',
        'Later normal Linux entry/MPU observation is distinct from the failed fastboot transfer.']}
 a.output.write_text(json.dumps(out,indent=2)+'\n');print(f'{len(records)} allowlisted log records, {len(ranges)} code ranges; no persistent value bytes published')
if __name__=='__main__':main()
