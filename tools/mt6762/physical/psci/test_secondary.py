#!/usr/bin/env python3
"""Compile actual MT6762 entry block; execute with modeled system registers.

Ordinary instructions/branches are original assembled bytes. MRS/MSR/ERET and
barriers are explicitly modeled: this does not prove physical EL2/GIC behavior.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm64_const as regs

ROOT=Path(__file__).resolve().parents[4]
text=(ROOT/'osfmk/arm64/start.s').read_text()
block=text.split('/* MT6762_PSCI_EL2_BEGIN:',1)[1].split('/* MT6762_PSCI_EL2_END */',1)[0]
block=block.split('*/',1)[1]
block=block.replace('EXT(LowSecondaryExceptionVectorBase)@pageoff',':lo12:LowSecondaryExceptionVectorBase')
block=block.replace('EXT(LowSecondaryExceptionVectorBase)@page','LowSecondaryExceptionVectorBase')
source='.arch armv8-a\n.text\n.global _start\n_start:\n'+block+'\n.global test_end\ntest_end:\nnop\n.balign 2048\nLowSecondaryExceptionVectorBase:\nnop\n'
clang=os.environ.get('IOS_CC','/home/iscle/mt6762-ios-port/toolchain/bin/clang')
with tempfile.TemporaryDirectory(prefix='mt6762-secondary-') as directory:
    path=Path(directory);(path/'test.s').write_text(source)
    subprocess.run([clang,'--target=aarch64-none-elf','-nostdlib','-fuse-ld=lld',
                    '-Wl,-Ttext=0x40000000','-Wl,--entry=_start',str(path/'test.s'),'-o',str(path/'test.elf')],check=True)
    with (path/'test.elf').open('rb') as stream:
        elf=ELFFile(stream)
        section=elf.get_section_by_name('.text');data=section.data();base=section['sh_addr']
        symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
instructions={i.address:i for i in md.disasm(data,base)}

def run(el=8,sctlr=0,gic=1,pmu=1,sre_failure=False):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(base,0x10000);u.mem_write(base,data)
    context=0x1122334455667788;u.reg_write(regs.UC_ARM64_REG_X0,context)
    system={'currentel':el,'sctlr_el2':sctlr,'cnthctl_el2':0x10,
            'id_aa64pfr0_el1':gic<<24,'icc_sre_el2':0,
            'midr_el1':0x410fd034,'mpidr_el1':0x80000103,
            'id_aa64dfr0_el1':pmu<<8,'pmcr_el0':6<<11}
    writes=[];reads=[];memory=[];eret=[];halt=[]
    def register(name):return getattr(regs,'UC_ARM64_REG_'+name.upper())
    def code(cpu,address,size,unused):
        if address==symbols['test_end']:cpu.emu_stop();return
        i=instructions[address];op=[x.strip() for x in i.op_str.split(',')]
        if i.mnemonic=='mrs':
            name=op[1].lower();reads.append(name)
            value=system[name]
            if name=='icc_sre_el2' and sre_failure:value=0
            cpu.reg_write(register(op[0]),value);cpu.reg_write(regs.UC_ARM64_REG_PC,address+4)
        elif i.mnemonic=='msr':
            name=op[0].lower();value=0 if op[1]=='xzr' else cpu.reg_read(register(op[1]))
            system[name]=value;writes.append((name,value));cpu.reg_write(regs.UC_ARM64_REG_PC,address+4)
        elif i.mnemonic=='eret':
            eret.append(system['spsr_el2']);system['currentel']=4
            cpu.reg_write(regs.UC_ARM64_REG_PC,system['elr_el2'])
        elif i.mnemonic in ('dsb','isb','ic'):
            cpu.reg_write(regs.UC_ARM64_REG_PC,address+4)
        elif i.mnemonic=='wfe':halt.append(True);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,code)
    u.hook_add(UC_HOOK_MEM_WRITE,lambda cpu,access,address,size,value,unused:memory.append(address))
    u.emu_start(base,base+len(data),count=500)
    assert u.reg_read(regs.UC_ARM64_REG_X0)==context and not memory
    good=el==4 or (el==8 and not(sctlr&((1<<0)|(1<<2)|(1<<25))) and not(gic and sre_failure))
    assert bool(halt)!=good
    if el==4:assert not writes and not eret
    elif good:
        assert eret==[0x3c5] and system['currentel']==4
        for key,value in {'hcr_el2':1<<31,'cnthctl_el2':0x13,'cntvoff_el2':0,
                          'sctlr_el1':0x30d00800,'cptr_el2':0x33ff,'hstr_el2':0,
                          'vttbr_el2':0,'sp_el1':0,'vpidr_el2':0x410fd034,
                          'vmpidr_el2':0x80000103,'mdcr_el2':6 if pmu else 0}.items():
            assert system[key]==value,(key,system.get(key))
        assert system['vbar_el2']==symbols['LowSecondaryExceptionVectorBase']
    if el not in (4,8) or (el==8 and sctlr&((1<<0)|(1<<2)|(1<<25))):assert not writes
    if not pmu:assert 'pmcr_el0' not in reads
    return good

for args in ({'el':4},{},{'gic':0},{'pmu':0},{'sctlr':1<<12},
             {'el':0},{'el':12},{'sctlr':1},{'sctlr':4},{'sctlr':1<<25},{'sre_failure':True}):run(**args)
print('PASS11 assembled secondary-entry cases: EL1 passthrough, EL2 descent, x0 preservation, unsafe-state rejection; system registers modeled')
