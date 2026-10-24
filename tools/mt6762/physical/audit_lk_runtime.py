#!/usr/bin/env python3
"""Read-only exact LK warning-state and image-cache audit; creates JSON only."""
import argparse,hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
LK_SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
RANGES=[('get_verity_status',0x48016650,0x480166d4),
 ('clear_verity_persistent_and_status',0x48016782,0x480167d4),
 ('warning_handler',0x48049b40,0x48049b7e),
 ('warning_clear_call',0x48049bd8,0x48049bfa),
 ('status_header_getter',0x48052934,0x4805294c),
 ('status_header_setter',0x48052994,0x480529c8),
 ('lock_header_getter',0x48052864,0x4805287c),
 ('header_authentication_write',0x48052728,0x48052774),
 ('cached_reason_getter',0x48042f10,0x48042f34),
 ('image_cache_lookup',0x48037b48,0x48037b8e),
 ('image_cache_allocate',0x48037c50,0x48037cc2),
 ('normal_loader_allocate_copy_decapsulate',0x48049f82,0x48049fc6)]
def sha(x):return hashlib.sha256(x).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--dump',required=True,type=Path);p.add_argument('--trial',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
 a=p.parse_args();b=(a.dump/'lk.bin').read_bytes();d=0x47fffe00
 if sha(b)!=LK_SHA:raise ValueError('Unexpected LK hash')
 md=Cs(CS_ARCH_ARM,CS_MODE_THUMB);md.detail=True;ranges=[]
 for name,start,end in RANGES:
  raw=b[start-d:end-d];ins=list(md.disasm(raw,start))
  if sum(i.size for i in ins)!=len(raw):raise ValueError('Incomplete range '+name)
  ranges.append({'name':name,'start':hex(start),'end':hex(end),'sha256':sha(raw),'instructions':[{'va':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in ins]})
 # Static fastboot registration function: resolve only r0 literal + PC-add.
 cmds=[];value=None
 for i in md.disasm(b[0x4801cfa0-d:0x4801d2d0-d],0x4801cfa0):
  if i.mnemonic.startswith('ldr') and i.op_str.startswith('r0, [pc,'):
   pool=((i.address+4)&~3)+i.operands[1].mem.disp;value=struct.unpack_from('<I',b,pool-d)[0]
  elif i.mnemonic=='add' and i.op_str=='r0, pc' and value is not None:value=(value+i.address+4)&0xffffffff
  elif i.mnemonic=='bl':
   if i.op_str=='#0x4801c788':
    if value is None or not 0<=value-d<len(b):raise ValueError('Unresolved command registration')
    off=value-d;cmds.append({'call_va':hex(i.address),'command':b[off:b.index(0,off)].decode()})
   value=None
 if len(cmds)!=25:raise ValueError('Unexpected registration count')
 xrefs=[];targets={0x48037c50,0x480166dc}
 for o in range(0x280,0x58000,2):
  if b[o+1]&0xf8!=0xf0:continue
  for i in md.disasm(b[o:o+4],d+o,count=1):
   if i.mnemonic in ('bl','b.w') and i.op_str.startswith('#0x') and int(i.op_str[1:],16) in targets:xrefs.append({'va':hex(i.address),'target':i.op_str[1:]})
 table=[]
 for n in range(2):
  va=0x480ab510+n*28;words=struct.unpack_from('<7I',b,va-d);names=[]
  for ptr in words[:3]:
   if ptr:names.append(b[ptr-d:b.index(0,ptr-d)].decode())
  table.append({'va':hex(va),'names':names,'image_pointer':hex(words[3]),'size':words[4],'allocate_callback':hex(words[5]),'free_callback':hex(words[6])})
 states=[]
 for name in ('seccfg-before.bin','seccfg-after.bin','seccfg-posttrial.bin'):
  raw=(a.trial/name).read_bytes();words=struct.unpack_from('<7I',raw)
  if words[:3]!=(0x4d4d4d4d,4,60) or words[6]!=0x45454545:raise ValueError('Unexpected seccfg header')
  states.append({'name':name,'sha256':sha(raw),'lock_state_at_0xc':words[3],'exact_lk_dm_verity_state_at_0x10':words[4],'runtime_word_at_0x14':words[5]})
 out={'authority':'Exact dumped LK instructions and captured state; no device reads/writes or patched payload.',
 'lk_sha256':LK_SHA,'bounded_code':ranges,'fastboot_static_registrations':cmds,'image_cache_table':table,
 'direct_call_scan':{'file_start':'0x280','file_end':'0x58000','stride':2,'targets':[hex(v) for v in sorted(targets)],'matches':xrefs,'limitation':'Direct Thumb BL/B.W references only; not a complete indirect-call graph.'},
 'seccfg_header_states':states,
 'findings':['The unlock operation changed exact-LK dm-verity status word0x10 from0 to1 before temporary boot.',
 'The current warning combines persisted status and AVB EIO; removing only AVB record is insufficient if status remains1.',
 'No explicit verity-clear command among25 recovered static registrations; not a proof about arbitrary indirect extensions.',
 'Only recovered direct cache-allocation caller is normal verified-image loader; fastboot does not populate it.',
 'RAM shim design must use allocation/copy/ownership equivalent to normal loader, not alias downloaded storage.'],
 'not_implemented':['No header reauthentication or seccfg restoration generator.','No RAM LK patch, device execution route or firmware write.']}
 a.output.write_text(json.dumps(out,indent=2)+'\n');print(f'{len(ranges)} decoded ranges, {len(cmds)} static commands, {len(xrefs)} selected direct calls')
if __name__=='__main__':main()
