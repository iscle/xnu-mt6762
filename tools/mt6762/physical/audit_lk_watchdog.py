#!/usr/bin/env python3
"""Read-only exact LK watchdog audit; execute original instructions on fake MMIO.

Only logging is intercepted. This never connects to a phone, supplies a boot
payload or models watchdog timing/reset acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_R0

SHA='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
DELTA=0x47fffe00
RANGES=[('early_platform_init_call',0x48002b90,0x48002ba0),
        ('download_boot_selector',0x4800302a,0x48003034),
        ('download_disable_and_jump',0x4800332e,0x4800337a),
        ('disable',0x48042f38,0x48042f4e),
        ('length',0x48042f50,0x48042f68),
        ('restart',0x48042f6c,0x48042f7c),
        ('watchdog_init',0x48043130,0x4804320e),
        ('kernel_final_interval_restart',0x4801bbc6,0x4801bbd4)]

def replay(blob,old_mode,selector):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(0x48000000,0x400000);u.mem_write(0x48000000,blob[0x200:])
    u.mem_map(0x10007000,0x1000);u.mem_map(0x60000000,0x10000)
    u.mem_write(0x10007000,struct.pack('<I',old_mode))
    u.mem_write(0x10007024,struct.pack('<I',selector))
    writes=[]
    def code(cpu,address,size,opaque):
        if address==0x48027ff8:cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    def write(cpu,access,address,size,value,opaque):
        if 0x10007000<=address<0x10008000:
            assert size==4
            writes.append({'address':hex(address),'value':hex(value)})
    u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_WRITE,write)
    def invoke(pc,r0=0):
        u.reg_write(UC_ARM_REG_SP,0x6000f000);u.reg_write(UC_ARM_REG_LR,0x60000001)
        u.reg_write(UC_ARM_REG_R0,r0);u.emu_start(pc|1,0x60000000,count=500)
        assert u.reg_read(UC_ARM_REG_PC)==0x60000000,'bounded invocation did not return'
    invoke(0x48043130)
    init=list(writes)
    mode_writes=[int(w['value'],16) for w in writes if w['address']=='0x10007000']
    expected0=(old_mode&~0x4f)|0x22000010
    expected1=(expected0&~2)|0x2200005d
    assert mode_writes==[expected0,expected1]
    assert expected1&1 and expected1&0x48==0x48
    assert {'address':'0x10007004','value':'0x5008'} in writes
    assert writes[-1]=={'address':'0x10007008','value':'0x1971'}
    writes.clear();invoke(0x48042f50,30);invoke(0x48042f6c)
    assert writes==[{'address':'0x10007004','value':'0xf008'},
                    {'address':'0x10007008','value':'0x1971'}]
    return {'initial_mode':hex(old_mode),'initial_nonrst2_selector':selector,
            'passed':True,'init_ordered_writes':init,'final_kernel_ordered_writes':writes,
            'final_mode_lower_bits':hex(expected1&0xffffff)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lk',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.resolve()==a.lk.resolve():p.error('output must not replace the input artifact')
    blob=a.lk.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=SHA:p.error('unsupported exact LK artifact')
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB);spans=[]
    for name,lo,hi in RANGES:
        data=blob[lo-DELTA:hi-DELTA]
        spans.append({'name':name,'start':hex(lo),'end':hex(hi),
                      'sha256':hashlib.sha256(data).hexdigest(),
                      'instructions':[{'address':hex(i.address),'instruction':i.mnemonic+' '+i.op_str}
                                      for i in md.disasm(data,lo)]})
    # Aligned Thumb BL/B.W candidates only; does not prove absence of indirect
    # calls, ARM veneers or secure-firmware MMIO writes outside this image.
    calls=[]
    for off in range(0x200,min(len(blob),0x80000),2):
        ins=next(md.disasm(blob[off:off+4],off+DELTA),None)
        if ins and ins.mnemonic in ('bl','b.w') and ins.op_str in ('#0x48042f38','#0x48043130'):
            calls.append({'address':hex(ins.address),'instruction':ins.mnemonic+' '+ins.op_str})
    assert calls==[{'address':'0x48002b98','instruction':'bl #0x48043130'},
                   {'address':'0x4800332e','instruction':'bl #0x48042f38'}]
    result={'artifact_sha256':SHA,'method':'Capstone bounded disassembly and Unicorn original Thumb execution; logging callback only intercepted; plain modeled MMIO.',
            'physical_hardware_tested':False,'rea_provider_unavailable':'inspect_firmware_regions requires unavailable caller-supplied Binwalk; no REA Evidence asserted.',
            'ranges':spans,'bounded_direct_call_scan':{'file_range':['0x200','0x80000'],'matches':calls},
            'cases':[replay(blob,m,s) for m in (0,0x64,0x7d) for s in (0,2,3,4)],
            'nominal_final_interval_seconds':30,
            'limitations':['No observation of actual watchdog enable/readback at kernel entry.',
                          'MODE enable is set by this exact normal LK init; DOWNLOAD_BOOT deliberately disables it before jump_da.',
                          'IRQ and dual-mode bits are set; IRQ_LEVEL bit5 is inherited. Secure interrupt routing, later firmware changes/feeding and physical timer clock are not modeled.',
                          '30seconds is programmed nominal interval, not an observed reset deadline; no exact30/60second reset promise.',
                          'Current DA MODE0x64 alone does not describe a fresh LK recovery entry; continuation must actually run this init path.']}
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS:12 exact-LK init cases and final30-second length/restart writes; no hardware execution')
if __name__=='__main__':main()
