#!/usr/bin/env python3
"""Offline exact preloader READ32 range-admission replay. No USB or RAM reads."""
import argparse, hashlib, json, struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
SHA='7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674';BASE=0x200710

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preloader',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
 a=p.parse_args();b=a.preloader.read_bytes()
 if hashlib.sha256(b).hexdigest()!=SHA:p.error('unsupported exact preloader')
 u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(0x200000,0x40000);u.mem_write(BASE,b[:0x40000-(BASE-0x200000)])
 u.mem_map(0x50000000,0x4000);u.mem_map(0x60000000,0x1000)
 cases=[]
 for addr,length,allowed in [(0x40084000,256,False),(0x40084000,4,False),(0x40200000,4,False),
   (0x10007000,0x1000,True),(0x10007ffc,8,False),(0x1001a080,4,True),
   (0x1001a080,8,False),(0x11c50000,0x1000,True),(0xfffffff0,32,False)]:
  for reg,val in [(UC_ARM_REG_SP,0x50003000),(UC_ARM_REG_LR,0x60000001),(UC_ARM_REG_R0,addr),(UC_ARM_REG_R1,length),(UC_ARM_REG_R2,1)]:u.reg_write(reg,val)
  u.emu_start(0x227911,0x60000000,count=300)
  assert u.reg_read(UC_ARM_REG_PC)==0x60000000
  status=u.reg_read(UC_ARM_REG_R0);assert (status==0)==allowed
  cases.append(dict(address=hex(addr),bytes=length,permitted=allowed,status=hex(status)))
 ranges=[]
 for name,lo,hi in [('read32_dispatch',0x202f9e,0x202fe0),('read32_check_and_load',0x2030d0,0x2030fa),('region_check',0x227888,0x227906)]:
  data=b[lo-BASE:hi-BASE];ins=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(data,lo))
  assert sum(i.size for i in ins)==len(data)
  ranges.append(dict(name=name,start=hex(lo),end_exclusive=hex(hi),sha256=hashlib.sha256(data).hexdigest(),instructions=[dict(va=hex(i.address),instruction=i.mnemonic+' '+i.op_str) for i in ins]))
 whitelist=[dict(start=hex(addr),bytes=hex(length)) for addr,length in struct.iter_unpack('<II',b[0x238e50-BASE:0x238e68-BASE])]
 result=dict(preloader_sha256=SHA,original_read_whitelist=whitelist,cases=cases,bounded_code=ranges,
   scope='Only original range comparisons execute; test addresses are never dereferenced. No USB command or MMIO.',
   conclusion='Exact stock preloader READ32 rejects trace DRAM before data transfer.',
   unknowns=['BROM READ32 policy is a different implementation and not audited here.','DRAM initialization/preservation before the USB loop is not proven.'])
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(cases))
if __name__=='__main__':main()
