#!/usr/bin/env python3
"""Execute bounded original NTC arithmetic offline, with explicit mock inputs."""
from pathlib import Path
import hashlib,json,struct,sys
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
b=Path(sys.argv[1]).read_bytes(); digest=hashlib.sha256(b).hexdigest()
assert digest=='82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
base=0xffffff8008080000
def signed(v): return v if v<0x80000000 else v-0x100000000
def run(ntc,vbif,current,fg,rfg,no_comp):
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(base,0x2000000);u.mem_write(base,b)
 u.mem_map(0x100000,0x10000);u.mem_map(0x300000,0x10000)
 u.reg_write(UC_ARM64_REG_SP,0x10f000);u.reg_write(UC_ARM64_REG_X0,0x300000)
 for off,val in [(0xa14,fg),(0xa1c,rfg),(0x82c4,no_comp),(0x82d0,16900),(0x82d4,1800)]:
  u.mem_write(0x300000+off,struct.pack('<I',val))
 u.mem_write(0x3082e0,struct.pack('<Q',0xffffff800987b7d8))
 observed={}
 def hook(uc,a,size,_):
  if a==0xffffff8008a7bbfc:
   observed.update(corrected_mv=signed(uc.reg_read(UC_ARM64_REG_W1)),pullup_correction_mv=signed(uc.reg_read(UC_ARM64_REG_W2)))
  if a==0xffffff8008a7bf44:
   observed['deci_c']=signed(uc.reg_read(UC_ARM64_REG_W0));uc.emu_stop();return
  if a in (0xffffff800809ef9c,0xffffff8008a7b010,0xffffff8008a7bd34):
   if a==0xffffff8008a7bd34:
    prop=uc.reg_read(UC_ARM64_REG_W0)
    value={1:current,8:ntc,9:vbif}[prop]
    uc.mem_write(uc.reg_read(UC_ARM64_REG_X1),struct.pack('<i',value))
   uc.reg_write(UC_ARM64_REG_W0,0);uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR));return
  if not (0xffffff8008a7bac0<=a<0xffffff8008a7bd34 or 0xffffff8008a7be28<=a<=0xffffff8008a7bf44):
   raise RuntimeError(f'unexpected execution {a:x}')
 u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0xffffff8008a7be28,0x200000,count=2000)
 assert 'deci_c' in observed
 return observed
rows=[]
for fg,rfg,no_comp in [(100,0,0),(100,0,1),(100,100,0),(100,100,1)]:
 for current in [-20000,-5000,0,5000,20000]:
  row=dict(ntc_mv=614,vbif_mv=1797,current_0p1ma=current,com_fg=fg,com_rfg=rfg,no_comp=no_comp)
  row.update(run(614,1797,current,fg,rfg,no_comp));rows.append(row)
print(json.dumps(dict(image_sha256=digest,physical_hardware_tested=False,
 method='Original force_get_tbat_internal arithmetic prefix, BattVoltToTemp and BattThermistorConverTemp ARM64; gauge property reads and profiling/debug hooks replaced. Explicit synthetic configurations; no real calibration claim.',cases=rows),indent=2))
