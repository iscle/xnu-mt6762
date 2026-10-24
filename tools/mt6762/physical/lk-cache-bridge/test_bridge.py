#!/usr/bin/env python3
"""Unicorn executes compiled shim and original LK cache allocator/lookup.

Only heap allocation, memcpy, fastboot response and final free are host hooks.
The original decapsulator executes its cache lookups through the first successful
header branch. No boot completion or physical execution is claimed.
"""
import argparse,hashlib,json,struct,unittest
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import *
from build import bl,LK_SHA
REGS=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_R12]
ARGS=None
class BridgeTests(unittest.TestCase):
 def run_case(self,mutate=None,reported=None,source=0x48b00000,alloc_fail=False,existing=False):
  image=bytearray(ARGS.boot.read_bytes())
  if mutate:mutate(image)
  size=len(image) if reported is None else reported
  lk=ARGS.lk.read_bytes();self.assertEqual(hashlib.sha256(lk).hexdigest(),LK_SHA)
  manifest=json.loads((ARGS.artifacts/'manifest.json').read_text());blob=(ARGS.artifacts/'bridge.bin').read_bytes()
  self.assertEqual(hashlib.sha256(blob).hexdigest(),manifest['blob_sha256'])
  u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
  u.mem_map(0x48000000,0x100000);u.mem_write(0x48000000,lk[512:])
  entry=int(manifest['placement']['address'],16);u.mem_map(entry,0x1000);u.mem_write(entry,blob)
  u.mem_write(0x4801dede,bytes.fromhex(manifest['patch']['replacement_hex']))
  u.mem_map(0x48b00000,(len(image)+4095)&~4095);u.mem_write(0x48b00000,bytes(image))
  u.mem_map(0x60000000,(len(image)+0x2ffff)&~4095)
  u.mem_map(0x70000000,0x10000);sp=0x70008000
  u.mem_map(0x71000000,0x1000);u.mem_write(0x71000000,b'\x00\xbe')
  original=[0x11110000+n*0x100 for n in range(13)]
  original[0]=source;original[4]=0x60000000;original[7]=source;original[9]=size
  for r,v in zip(REGS,original):u.reg_write(r,v)
  u.reg_write(UC_ARM_REG_SP,sp);u.reg_write(UC_ARM_REG_LR,0x71000001)
  saved=[0x22220000+n*0x100 for n in range(8)]+[0x71000001]
  u.mem_write(sp+0x74,struct.pack('<9I',*saved))
  events={'allocate':0,'copy':0,'free':[],'fail':0,'decap':False,'cached_lookup':False,'returned':False}
  if existing:
   u.mem_write(0x480ab51c,struct.pack('<II',0x60008000,4096))
  def ret(value=None):
   if value is not None:u.reg_write(UC_ARM_REG_R0,value)
   u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
  def hook(uc,pc,n,_):
   if pc==0x4800419c:
    events['allocate']+=1;self.assertEqual(uc.reg_read(UC_ARM_REG_R0),size);self.assertEqual(uc.reg_read(UC_ARM_REG_SP)%8,0);ret(0 if alloc_fail else 0x60010000)
   elif pc==0x48028e24:
    dst=uc.reg_read(UC_ARM_REG_R0);src=uc.reg_read(UC_ARM_REG_R1);count=uc.reg_read(UC_ARM_REG_R2)
    self.assertEqual((dst,src,count),(0x60010000,source,size));uc.mem_write(dst,bytes(uc.mem_read(src,count)));events['copy']+=1;ret(dst)
   elif pc in (0x48028ca4,0x48037b44):
    events['free'].append(uc.reg_read(UC_ARM_REG_R0));ret()
   elif pc==0x480175dc:ret(0)
   elif pc==0x4801cbb8:
    events['fail']+=1;self.assertEqual(uc.reg_read(UC_ARM_REG_SP)%8,0);ret()
   elif pc==0x48036f38:
    events['decap']=True
    self.assertEqual(uc.reg_read(UC_ARM_REG_SP),sp)
    self.assertEqual(uc.reg_read(UC_ARM_REG_LR),0x4801dee3)
    for i in range(4,12):self.assertEqual(uc.reg_read(REGS[i]),original[i])
    ptr,count=struct.unpack('<II',uc.mem_read(0x480ab51c,8));self.assertEqual((ptr,count),(0x60010000,size));self.assertEqual(bytes(uc.mem_read(ptr,size)),bytes(image))
   elif pc==0x48036f68:
    self.assertEqual(uc.reg_read(UC_ARM_REG_R4),0x60010000);events['cached_lookup']=True;uc.emu_stop()
   elif pc==0x71000000:
    events['returned']=True;self.assertEqual(uc.reg_read(UC_ARM_REG_SP),sp+0x98)
    for r,v in zip(REGS[4:12],saved[:8]):self.assertEqual(uc.reg_read(r),v)
    uc.emu_stop()
  u.hook_add(UC_HOOK_CODE,hook)
  u.emu_start(0x4801dede|1,0,count=20000)
  self.assertTrue(events['returned'] or events['cached_lookup'])
  return events
 def test_actual_diagnostic_image(self):
  e=self.run_case();self.assertTrue(e['cached_lookup']);self.assertEqual((e['allocate'],e['copy'],e['fail']),(1,1,0));self.assertEqual(e['free'],[])
 def test_existing_cache_freed_by_original_allocator(self):
  e=self.run_case(existing=True);self.assertTrue(e['cached_lookup']);self.assertEqual(e['free'],[0x60008000])
 def test_allocator_failure_uses_original_cleanup(self):
  e=self.run_case(alloc_fail=True);self.assertEqual((e['allocate'],e['copy'],e['fail']),(1,0,1));self.assertEqual(e['free'],[0x60000000]);self.assertFalse(e['decap'])
 def test_replacement_allocation_failure_releases_old_cache(self):
  e=self.run_case(alloc_fail=True,existing=True);self.assertEqual(e['free'],[0x60008000,0x60000000]);self.assertFalse(e['decap']);self.assertEqual(e['fail'],1)
 def test_invalid_inputs_reject_without_allocator(self):
  cases=[('magic',lambda b:b.__setitem__(0,0),None,0x48b00000),
   ('version',lambda b:struct.pack_into('<I',b,40,3),None,0x48b00000),
   ('header-size',lambda b:struct.pack_into('<I',b,1644,0),None,0x48b00000),
   ('page',lambda b:struct.pack_into('<I',b,36,3000),None,0x48b00000),
   ('overflow-kernel',lambda b:struct.pack_into('<I',b,8,0xffffffff),None,0x48b00000),
   ('zero-kernel',lambda b:struct.pack_into('<I',b,8,0),None,0x48b00000),
   ('zero-dtb',lambda b:struct.pack_into('<I',b,1648,0),None,0x48b00000),
   ('second-stage',lambda b:struct.pack_into('<I',b,24,1),None,0x48b00000),
   ('recovery-offset',lambda b:(struct.pack_into('<I',b,1632,1),struct.pack_into('<Q',b,1636,0)),None,0x48b00000),
   ('short',None,1659,0x48b00000),('too-large',None,0x08000001,0x48b00000),
   ('truncated',None,len(ARGS.boot.read_bytes())-4096,0x48b00000),('wrong-source',None,None,0x48a00000)]
  for name,mutate,size,source in cases:
   with self.subTest(name=name):
    e=self.run_case(mutate,size,source);self.assertEqual((e['allocate'],e['copy'],e['fail']),(0,0,1));self.assertTrue(e['returned']);self.assertEqual(e['free'],[0x60000000])
 def test_branch_encoding_exact_original(self):self.assertEqual(bl(0x4801dede,0x48036f38).hex(),'19f02bf8')
 def test_branch_bounds(self):
  for target in (0x4801dede+4+(1<<24),0x4801dede+4-(1<<24)-2,0x48200001):
   with self.assertRaises(ValueError):bl(0x4801dede,target)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--lk',required=True,type=Path);p.add_argument('--boot',required=True,type=Path);p.add_argument('--artifacts',required=True,type=Path);ARGS,rest=p.parse_known_args();unittest.main(argv=['test_bridge.py',*rest])
