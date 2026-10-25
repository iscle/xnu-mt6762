#!/usr/bin/env python3
"""Execute exact LK BCB consumer with synthetic read-only partition bytes.

No device access, no output boot marker/partition image. Storage read is a model.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import *
SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lk',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();lk=a.lk.read_bytes()
 if hashlib.sha256(lk).hexdigest()!=SHA:raise ValueError('Wrong LK')
 results=[]
 for command,expected in [('boot-recovery',2),('boot-fastboot',2),('bootonce-bootloader',0),('',0)]:
  backing=bytearray(6144);backing[:len(command)]=command.encode();backing[32:]=bytes([0xa5])*(6144-32)
  u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(0x48000000,0x100000);u.mem_write(0x48000000,lk[512:]);u.mem_map(0x60000000,0x20000)
  u.reg_write(UC_ARM_REG_SP,0x60018000);u.reg_write(UC_ARM_REG_LR,0x60002001);u.mem_write(0x480af5cc,struct.pack('<I',0));reads=[];returned=[]
  def ret(v=0):u.reg_write(UC_ARM_REG_R0,v);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
  def hook(uc,pc,n,_):
   if pc==0x48028c70:
    if uc.reg_read(UC_ARM_REG_R0)!=6144:raise ValueError('Unexpected allocation')
    ret(0x60004000)
   elif pc in (0x480175dc,0x480429e8,0x4803ecb8,0x48028ca4):ret()
   elif pc==0x4803fcc4:
    name=bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0),5));offset=uc.reg_read(UC_ARM_REG_R2)|(uc.reg_read(UC_ARM_REG_R3)<<32)
    buf,size=struct.unpack('<II',uc.mem_read(uc.reg_read(UC_ARM_REG_SP),8))
    if (name,offset,size)!=(b'para\0',0,6144):raise ValueError('Wrong exact storage request')
    reads.append({'partition':'para','byte_offset':offset,'size':size});uc.mem_write(buf,bytes(backing));ret(size)
   elif pc==0x60002000:
    returned.append(uc.reg_read(UC_ARM_REG_R0));uc.emu_stop()
  u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x48017e39,0,count=30000)
  mode=struct.unpack('<I',u.mem_read(0x480af5cc,4))[0]
  if mode!=expected or returned!=[int(bool(expected))] or len(reads)!=1:raise ValueError('Unexpected consumer result')
  if bytes(u.mem_read(0x60004000,6144))!=bytes(backing):raise ValueError('Consumer modified read buffer')
  results.append({'synthetic_command':command,'reads':reads,'return':returned[0],'boot_mode':mode,'buffer_unchanged':True})
 ranges=[]
 for name,start,end in [('consumer',0x48017e38,0x48017ea0),('partition_name_loader',0x48003d08,0x48003d44),('offset_zero_reader',0x48003c34,0x48003c9e),('boot_mode_callsite',0x480038e0,0x480038f0)]:
  raw=lk[start-0x47fffe00:end-0x47fffe00];ins=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(raw,start))
  if sum(i.size for i in ins)!=len(raw):raise ValueError('Incomplete decode')
  ranges.append({'name':name,'start':hex(start),'end':hex(end),'sha256':hashlib.sha256(raw).hexdigest(),'instructions':[{'va':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in ins]})
 result={'authority':'Offline synthetic BCB bytes, exact LK consumer/reader/libc. No phone or partition mutation.', 'lk_sha256':SHA,'results':results,'bounded_code':ranges,'bootonce_bootloader_literal_present':b'bootonce-bootloader' in lk,'command_offset':0,'command_field_size':32,'clear_behavior':'No storage-write call in consumer; accepted marker remains persistent.','limits':['Boot-mode priorities before this consumer can select another route.','Actual para GPT bounds and fresh backup must be verified separately.','XNU diagnostic does not clear Android BCB.','No complete reboot or recovery execution proved.']}
 a.output.write_text(json.dumps(result,indent=2)+'\n');print('Four exact-consumer cases passed; para offset0 read6144; accepted marker not cleared')
if __name__=='__main__':main()
