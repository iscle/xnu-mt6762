#!/usr/bin/env python3
"""Execute bounded original LK reset instructions against modeled RAM/MMIO only."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
DELTA=0x47fffe00
SPANS=[('mtk_arch_reset',0x48043274,0x4804333e),('pwrap_disable',0x48005f50,0x48005f70),('udelay_thunk',0x48042a90,0x48042a94),('us_to_13MHz_ticks',0x4804290c,0x48042926)]
SOURCES=['vendor/mediatek/proprietary/bootable/bootloader/lk/platform/mt6765/mtk_wdt.c',
         'vendor/mediatek/proprietary/bootable/bootloader/lk/platform/mt6765/include/platform/mtk_wdt.h']

def digest(b):return hashlib.sha256(b).hexdigest()
def check(blob,mode,status,old_mode,old_nonrst,old_latch):
 u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
 u.mem_map(0x48000000,0x100000);u.mem_write(0x48000000,blob[0x200:])
 for addr,size in [(0x10007000,0x1000),(0x1000d000,0x1000),(0x60000000,0x10000)]:u.mem_map(addr,size)
 for addr,val in [(0x10007000,old_mode),(0x10007024,old_nonrst),(0x10007048,old_latch),(0x1000700c,status),(0x1000d004,1)]:u.mem_write(addr,struct.pack('<I',val))
 trace=[]
 def code(uc,addr,size,unused):
  if addr in (0x48027ff8,0x48042a1c,0x48042a90):
   if addr!=0x48027ff8:trace.append({'delay': 'us','amount':uc.reg_read(UC_ARM_REG_R0)})
   uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
 def write(uc,access,addr,size,value,unused):
  if 0x10000000<=addr<0x20000000:
   assert size==4
   trace.append({'address':hex(addr),'value':hex(value)})
   if addr==0x10007014:uc.emu_stop()
 u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_WRITE,write)
 u.reg_write(UC_ARM_REG_R0,mode);u.reg_write(UC_ARM_REG_SP,0x6000f000)
 u.emu_start(0x48043275,0,count=2000)
 expected=[{'address':'0x10007008','value':'0x1971'},
           {'address':'0x10007000','value':hex((old_mode&~0x58)|0x22000004)},
           {'address':'0x10007024','value':hex((old_nonrst&~0x2000)|(0x2000 if mode else 0))}]
 if not status:expected.append({'address':'0x10007048','value':hex((old_latch&~0x20000)|0x95000000)})
 expected += [{'delay':'us','amount':100},{'address':'0x1000d004','value':'0x0'},
              {'delay':'us','amount':10},{'address':'0x10007014','value':'0x1209'}]
 assert trace==expected,(trace,expected)
 return {'mode':mode,'status':hex(status),'initial_mode':hex(old_mode),'initial_nonrst2':hex(old_nonrst),
         'initial_latch_ctl2':hex(old_latch),'passed':True,'ordered_trace':trace}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lk',required=True,type=Path)
 p.add_argument('--bsp',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
 a=p.parse_args();blob=a.lk.read_bytes()
 if digest(blob)!=SHA:p.error('unsupported stock LK digest')
 md=Cs(CS_ARCH_ARM,CS_MODE_THUMB);spans=[]
 for name,lo,hi in SPANS:
  data=blob[lo-DELTA:hi-DELTA];inst=list(md.disasm(data,lo))
  assert sum(i.size for i in inst)==len(data)
  spans.append({'name':name,'start':hex(lo),'end_exclusive':hex(hi),'sha256':digest(data),
                'instructions':[{'va':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in inst]})
 cases=[]
 for mode in (0,1):
  for status in (0,0x40000000):
   for seed in (0,0xa5a5ffff):cases.append(check(blob,mode,status,seed,seed,seed))
 result={'lk_sha256':SHA,'bounded_original_code':spans,
         'bsp_reference':[{'path':s,'sha256':digest((a.bsp/s).read_bytes())} for s in SOURCES],
         'cases':cases,'modeled_callbacks':['dprintf noop','gpt_busy_wait_us records requested delay','udelay thunk records requested delay'],
         'limitations':['Only original LK AP instruction sequence executes; no reset, DA or peripheral is executed.',
                        'Model does not prove WDT acceptance or PMIC/DRAM retention from DA state.',
                        'Exact preloader consumption of NONRST2 bit13 and resulting boot reason not established here.',
                        'This script produces evidence only and contains no phone connection or write interface.']}
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(f'{len(cases)} original reset cases passed')
if __name__=='__main__':main()
