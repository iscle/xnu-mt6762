#!/usr/bin/env python3
"""Known-image offline arithmetic fixture; mocked register reads, no device I/O."""
from pathlib import Path
import hashlib,json,struct,sys
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
b=Path(sys.argv[1]).read_bytes();digest=hashlib.sha256(b).hexdigest()
assert digest=='82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
base=0xffffff8008080000
def run(current,low,high,rfg,tune,charge):
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(base,0x2000000);u.mem_write(base,b)
 u.mem_map(0x100000,0x10000);u.mem_map(0x300000,0x10000)
 u.reg_write(UC_ARM64_REG_SP,0x10f000);u.reg_write(UC_ARM64_REG_LR,0x200000)
 u.reg_write(UC_ARM64_REG_X0,0x300000);u.reg_write(UC_ARM64_REG_X2,0x301000)
 u.mem_write(0x300110,struct.pack('<II',rfg,tune))
 calls=[]
 def hook(uc,a,size,_):
  if a in (0xffffff800809ef9c,0xffffff8008125b2c,0xffffff8008a7b010,
           0xffffff8008a84e08,0xffffff8008a84ed0,0xffffff800865809c):
   if a==0xffffff800865809c:
    reg=uc.reg_read(UC_ARM64_REG_W1);calls.append(reg)
    value={0xd8a:current,0xd12:low,0xd14:high}[reg]
    uc.mem_write(uc.reg_read(UC_ARM64_REG_X2),struct.pack('<I',value))
   uc.reg_write(UC_ARM64_REG_W0,0);uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR))
  elif not (0xffffff8008a85000<=a<=0xffffff8008a850b4 or
            0xffffff8008a85344<=a<=0xffffff8008a85564 or
            0xffffff8008a863d0<=a<=0xffffff8008a864a8):
   raise RuntimeError(f'unexpected execution {a:x}')
 u.hook_add(UC_HOOK_CODE,hook)
 u.emu_start(0xffffff8008a85344 if charge else 0xffffff8008a85000,0x200000,count=1000)
 assert u.reg_read(UC_ARM64_REG_PC)==0x200000
 if charge:return struct.unpack('<i',u.mem_read(0x301000,4))[0]*100
 value=u.reg_read(UC_ARM64_REG_W0)
 return (value if value<0x80000000 else value-0x100000000)*100
rows=[]
for rfg,tune in [(100,1000),(200,1500),(75,900)]:
 for raw in [0,1,100,0x7fff,0x8000,0xff9b,0xffff]:
  rows.append(dict(current=raw,low=(raw*5)&65535,high=raw,rfg=rfg,tune=tune,
   ua=run(raw,0,0,rfg,tune,False),uah=run(0,(raw*5)&65535,raw,rfg,tune,True)))
print(json.dumps(dict(image_sha256=digest,physical_hardware_tested=False,
 method='Original instant_current/reg_to_current/coulomb_get ARM64; known register reads and latch/profiling/log calls intercepted',cases=rows),indent=2))
