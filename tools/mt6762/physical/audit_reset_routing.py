#!/usr/bin/env python3
"""Pinned preloader/DA reset-routing audit; modeled RAM/MMIO only, no USB."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_PC,UC_ARM_REG_SP,UC_ARM_REG_LR,
    UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_C1_C0_2,UC_ARM_REG_FPEXC)

PL_SHA='7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674'
DA_SHA='658ff869c301fadc1a84a9409a55b5b5bdcf01524a1f904aad29a89a07ef2dec'
LOADER_SHA='aef234190ccb8145d2e3b8459741e9adb70f2caa8481aa216c1b25152afaca1f'

def sha(b):return hashlib.sha256(b).hexdigest()
def ret(u,value=None):
    if value is not None:u.reg_write(UC_ARM_REG_R0,value)
    u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
def da_cpu(blob):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(0x40000000,0x100000);u.mem_write(0x40000000,blob)
    u.mem_map(0x60000000,0x10000);u.reg_write(UC_ARM_REG_SP,0x6000f000)
    u.reg_write(UC_ARM_REG_LR,0x60000001)
    u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);u.reg_write(UC_ARM_REG_FPEXC,1<<30)
    return u

def preloader_safe_mode(blob,en,timeout):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(0x200000,0x500000);u.mem_write(0x200710,blob)
    u.mem_map(0x1001a000,0x1000);u.mem_map(0x60000000,0x10000)
    u.reg_write(UC_ARM_REG_SP,0x6000f000);u.reg_write(UC_ARM_REG_LR,0x60000001)
    u.reg_write(UC_ARM_REG_R0,en);u.reg_write(UC_ARM_REG_R1,timeout)
    u.mem_write(0x1001a108,struct.pack('<I',0x20));writes=[]
    def write(cpu,access,address,size,value,opaque):
        if 0x1001a000<=address<0x1001b000:
            assert size==4;writes.append({'address':hex(address),'value':hex(value)})
    u.hook_add(UC_HOOK_MEM_WRITE,write)
    u.emu_start(0x223aa5,0x60000000,count=2000)
    assert u.reg_read(UC_ARM_REG_PC)==0x60000000
    flag=0x444c0000|(((timeout//1000 if timeout else 0x3fff)<<2)&0xfffc)|bool(en)
    assert writes==[{'address':'0x1001a100','value':'0xad98'},
                    {'address':'0x1001a108','value':'0x21'},
                    {'address':'0x1001a100','value':'0x0'},
                    {'address':'0x1001a080','value':hex(flag)}]
    return {'en':en,'timeout_input_ms':timeout,'writes':writes,'passed':True}

def shutdown_dispatch(blob,bootmode,enablewdt):
    """Execute actual dispatcher; mock transport, USB/RTC and delay callbacks.

    Keep both original board-capability functions (which return zero). Stop at
    actual WDT callback entry or final shutdown loop, before hardware effects.
    """
    u=da_cpu(blob);u.reg_write(UC_ARM_REG_R0,0x60000100)
    u.mem_write(0x60000100,struct.pack('<II',0x60000201,0x60000205))
    flags=int(bootmode!=0);fields=[flags,enablewdt,0,bootmode,0,0,0,0]
    calls=[];terminal=[]
    def code(cpu,address,size,opaque):
        if address==0x40003c60:ret(cpu,3)
        elif address==0x4000abb0:ret(cpu,0)
        elif address==0x60000200:
            dest=cpu.reg_read(UC_ARM_REG_R0);length=cpu.reg_read(UC_ARM_REG_R1)
            count=struct.unpack('<I',cpu.mem_read(length,4))[0]
            assert count==28;cpu.mem_write(dest,struct.pack('<8I',*fields)[:count]);ret(cpu,0)
        elif address in (0x60000204,0x4000f20c,0x4000c11a):ret(cpu,0)
        elif address==0x4000e9a8:ret(cpu,1) # Explicit modeled connected-USB status.
        elif address==0x4000e930:
            calls.append({'callback':'usb_disconnect','r0':cpu.reg_read(UC_ARM_REG_R0),'r1':cpu.reg_read(UC_ARM_REG_R1)});ret(cpu,0)
        elif address==0x40017544:
            calls.append({'callback':'rtc_reset_time'});ret(cpu,0)
        elif address==0x40017450:
            calls.append({'callback':'watchdog_reset','r0':cpu.reg_read(UC_ARM_REG_R0),'r1':cpu.reg_read(UC_ARM_REG_R1)})
            terminal.append('watchdog_callback');cpu.emu_stop()
        elif address==0x400055fc:terminal.append('shutdown_loop');cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,code);u.emu_start(0x400054ad,0,count=2000)
    assert calls[:2]==[{'callback':'usb_disconnect','r0':3,'r1':0},{'callback':'rtc_reset_time'}]
    if bootmode==0:assert terminal==['shutdown_loop'] and len(calls)==2
    else:
        assert terminal==['watchdog_callback']
        assert calls[-1]=={'callback':'watchdog_reset','r0':enablewdt,'r1':1 if bootmode==1 else 16}
    return {'transmitted_u32_fields':fields,'callbacks':calls,'terminal':terminal[0],'passed':True}

def da_watchdog(blob,first_arg):
    u=da_cpu(blob);u.mem_map(0x10007000,0x1000);u.mem_map(0x1001a000,0x1000)
    for address,value in [(0x10007000,0x64),(0x10007024,0x20002000),(0x1001a080,0x444cfffc)]:
        u.mem_write(address,struct.pack('<I',value))
    u.reg_write(UC_ARM_REG_R0,first_arg);u.reg_write(UC_ARM_REG_R1,1)
    events=[]
    def code(cpu,address,size,opaque):
        if address==0x40003c60:ret(cpu,3)
        elif address==0x4000abb0:ret(cpu,0)
        elif address==0x4000c11a:
            events.append({'delay_callback_arg':cpu.reg_read(UC_ARM_REG_R0)});ret(cpu,0)
    def write(cpu,access,address,size,value,opaque):
        if 0x10000000<=address<0x20000000:
            assert size==4;events.append({'address':hex(address),'value':hex(value)})
            if address==0x10007014:cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_WRITE,write)
    u.emu_start(0x400170a1,0,count=1000)
    assert events==[{'address':'0x10007048','value':'0x95000000'},
                    {'address':'0x10007000','value':'0x22000004'},
                    {'address':'0x1001a080','value':'0x0'},
                    {'delay_callback_arg':0},
                    {'address':'0x10007014','value':'0x1209'}]
    return {'first_argument':first_arg,'flags_argument':1,'events':events,'passed':True}

def disassemble(blob,delta,ranges):
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB);out=[]
    for name,lo,hi in ranges:
        data=blob[lo-delta:hi-delta]
        out.append({'name':name,'start':hex(lo),'end':hex(hi),'sha256':sha(data),
                    'instructions':[{'address':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in md.disasm(data,lo)]})
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preloader',type=Path,required=True)
    p.add_argument('--loader',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.resolve() in (a.preloader.resolve(),a.loader.resolve()):p.error('output must not replace input')
    pl=a.preloader.read_bytes();loader=a.loader.read_bytes();da=loader[0x7538a4:0x7538a4+0x5118c]
    if (sha(pl),sha(loader),sha(da))!=(PL_SHA,LOADER_SHA,DA_SHA):p.error('unsupported artifact identity')
    result={'physical_hardware_tested':False,'artifact_sha256':{'preloader':PL_SHA,'loader':LOADER_SHA,'da2':DA_SHA},
      'preloader_safe_mode_cases':[preloader_safe_mode(pl,en,t) for en in (0,1) for t in (0,5000)],
      'shutdown_dispatch_cases':[shutdown_dispatch(da,m,e) for m,e in [(0,0),(1,0),(1,1),(2,0)]],
      'da_watchdog_cases':[da_watchdog(da,x) for x in (0,1)],
      'preloader_ranges':disassemble(pl,0x200710,[('platform_safe_mode',0x223aa4,0x223aee),('initial_safe_mode_enable',0x21c4f8,0x21c502),('jump_safe_mode_disable_a',0x21c3ee,0x21c3fa),('jump_safe_mode_disable_b',0x21c452,0x21c462)]),
      'da_ranges':disassemble(da,0x40000000,[('shutdown_command',0x400054ac,0x40005616),('watchdog_reset',0x400170a0,0x40017186),('watchdog_thunk',0x40017450,0x40017454),('board_capabilities',0x4003a3ec,0x4003a3f4)]),
      'limitations':['Controlled software execution, not a physical reset or boot observation.','Original DA2 is pinned; any current transformed DA must separately prove these code ranges unchanged.','Transport, USB, RTC and delay callbacks are modeled; their physical side effects are not executed.','BROM code and reset-retention semantics not audited; flag difference does not prove cause or remedy.','Transient BROM enumeration can precede normal boot per user observation; it is not failure evidence by itself.','BCB recovery is a later LK decision; neither USB identity nor reset ACK proves LK consumed it.']}
    a.output.write_text(json.dumps(result,indent=2)+'\n');print('PASS:4 preloader encodings,4 original DA dispatch paths,2 original DA reset traces; no phone I/O')
if __name__=='__main__':main()
