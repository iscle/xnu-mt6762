#!/usr/bin/env python3
"""Read-only recovery packaging and exact LK verifier/branch CPU checks."""
import argparse,hashlib,json,struct
from pathlib import Path
import bootimg
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import *
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
LK_SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lk',required=True,type=Path);p.add_argument('--stock',required=True,type=Path);p.add_argument('--candidate',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 lk=a.lk.read_bytes();stock=a.stock.read_bytes();candidate=a.candidate.read_bytes()
 if sha(lk)!=LK_SHA:raise ValueError('Unexpected LK')
 old=bootimg.parse(stock);new=bootimg.parse(candidate)
 if len(candidate)!=len(stock) or len(candidate)!=33554432:raise ValueError('Partition-size mismatch')
 for name in ('dtb','recovery_dtbo'):
  if old.parts[name]!=new.parts[name]:raise ValueError('Stock DT component changed: '+name)
 off,size=struct.unpack_from('>QQ',candidate,len(candidate)-64+20);vbmeta=candidate[off:off+size]
 if len(vbmeta)!=size or vbmeta[:4]!=b'AVB0':raise ValueError('Invalid footer/header')
 u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(0x48000000,0x100000);u.mem_write(0x48000000,lk[512:]);u.mem_map(0x60000000,0x20000);u.mem_write(0x60000000,vbmeta)
 for reg,val in [(UC_ARM_REG_SP,0x60018000),(UC_ARM_REG_R0,0x60000000),(UC_ARM_REG_R1,size),(UC_ARM_REG_R2,0x60001000),(UC_ARM_REG_R3,0x60001004),(UC_ARM_REG_LR,0x60002001)]:u.reg_write(reg,val)
 result=[]
 def done(uc,pc,n,_):
  if pc==0x60002000:result.append(uc.reg_read(UC_ARM_REG_R0));uc.emu_stop()
 hook=u.hook_add(UC_HOOK_CODE,done);u.emu_start(0x48048bf1,0,count=100000);u.hook_del(hook)
 if result!=[1]:raise ValueError('Expected exact LK OK_NOT_SIGNED')
 branches=[]
 for allowed in (0,1):
  u.reg_write(UC_ARM_REG_SP,0x60018000);u.mem_write(0x60018568,struct.pack('<I',allowed));stops=[]
  def branch(uc,pc,n,_):
   if pc in (0x480464b4,0x480465ec):stops.append(pc);uc.emu_stop()
  hook=u.hook_add(UC_HOOK_CODE,branch);u.emu_start(0x480465e3,0,count=20);u.hook_del(hook)
  expected=0x480465ec if allowed else 0x480464b4
  if stops!=[expected]:raise ValueError('Unexpected verification-policy branch')
  branches.append({'allow_verification_error':allowed,'next_pc':hex(expected)})
 ranges=[]
 for name,start,end in [('recovery_slot_flags',0x48049e18,0x48049e48),('populate_cache',0x48049f82,0x48049fc6),('unsigned_policy_branch',0x480465e2,0x480465ec),('reboot_recovery',0x4801db90,0x4801dbbe),('rtc_marker',0x4800839c,0x480083e2)]:
  raw=lk[start-0x47fffe00:end-0x47fffe00];ins=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(raw,start))
  if sum(i.size for i in ins)!=len(raw):raise ValueError('Incomplete disassembly')
  ranges.append({'name':name,'start':hex(start),'end':hex(end),'sha256':sha(raw),'instructions':[{'va':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in ins]})
 out={'authority':'Offline exact LK CPU checks and image parser; no phone actions/full boot.', 'lk_sha256':LK_SHA,'stock_sha256':sha(stock),'candidate_sha256':sha(candidate),'partition_size':len(candidate),'page_size':new.page_size,'preserved_parts':{n:{'size':len(new.parts[n]),'sha256':sha(new.parts[n])} for n in ('dtb','recovery_dtbo')},'candidate_part_sizes':{k:len(v) for k,v in new.parts.items()},'vbmeta':{'offset':off,'size':size,'algorithm':struct.unpack_from('>I',vbmeta,28)[0],'flags':struct.unpack_from('>I',vbmeta,120)[0]},'exact_verifier_return':result[0],'result_name':'OK_NOT_SIGNED, not full acceptance','allow_error_branch_checks':branches,'bounded_code':ranges,'remaining_unknowns':['Current physical recovery authentication-policy result not observed.','Main vbmeta flags3 do not establish recovery policy; exact recovery requests NO_VBMETA_PARTITION.','No complete AVB partition I/O, LK boot, RTC reset or XNU execution modeled.']}
 a.output.write_text(json.dumps(out,indent=2)+'\n');print('Stock DT components preserved; exact verifier returned OK_NOT_SIGNED; both policy branches passed')
if __name__=='__main__':main()
