#!/usr/bin/env python3
"""Bounded instruction/path/ABI replay; display, WDT and timer callees mocked."""
import argparse,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import *
from patch import patch,BASE,SITE,OFFSET,BEFORE,AFTER,digest

def run(b,state=2,direct=False):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(0x47fff000,0x102000);u.mem_write(BASE,b)
    u.mem_map(0x50000000,0x10000)
    sp=0x50008000;end=0x50009000
    # Dispatcher: literal + ADD PC => pointer-to-state location.
    pp=struct.unpack_from('<I',b,0x48037ac0-BASE)[0]+0x48037a8c
    u.mem_write(pp,struct.pack('<I',0x50000000));u.mem_write(0x50000000,struct.pack('<I',state))
    regs=[UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11]
    initial=[0x12340000+i for i in range(8)]
    for r,v in zip(regs,initial):u.reg_write(r,v)
    u.reg_write(UC_ARM_REG_R0,0);u.reg_write(UC_ARM_REG_SP,sp);u.reg_write(UC_ARM_REG_LR,end|1)
    events=[];done=[]
    names={0x48027d78:'clean',0x48027d6c:'rows',0x48027d30:'cursor',0x48027d08:'printf',0x48042f6c:'watchdog',0x48042a8c:'delay_ms',0x480379b4:'other_warning'}
    def hook(uc,addr,size,data):
        if addr==end:done.append(True);uc.emu_stop();return
        if addr not in names:return
        assert uc.reg_read(UC_ARM_REG_SP)%8==0
        name=names[addr];r0=uc.reg_read(UC_ARM_REG_R0)
        if name=='printf':
            s=bytes(uc.mem_read(r0,160)).split(b'\0')[0].decode('ascii');events.append([name,s])
        elif name=='cursor':events.append([name,r0,uc.reg_read(UC_ARM_REG_R1)])
        elif name=='delay_ms':events.append([name,r0])
        else:events.append([name])
        uc.reg_write(UC_ARM_REG_R0,24 if name=='rows' else 0)
        uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start((0x48037964 if direct else 0x48037a84)|1,end+4,count=500)
    assert done and u.reg_read(UC_ARM_REG_SP)==sp
    assert [u.reg_read(r) for r in regs]==initial
    return {'events':events,'return':u.reg_read(UC_ARM_REG_R0)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--stock',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    b=a.stock.read_bytes();q=patch(b);assert a.candidate.read_bytes()==q
    c=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    old=list(c.disasm(b[OFFSET:OFFSET+4],SITE));new=list(c.disasm(q[OFFSET:OFFSET+4],SITE))
    assert len(old)==1 and old[0].mnemonic=='bl' and old[0].op_str=='#0x48042a8c'
    assert [(i.mnemonic,i.size) for i in new]==[('nop',2),('nop',2)]
    cases=[]
    for state in range(5):
        x,y=run(b,state),run(q,state)
        if state==2:
            assert [e for e in x['events'] if e[0]!='delay_ms']==y['events']
            assert [e for e in x['events'] if e[0]=='delay_ms']==[['delay_ms',5000]]
            assert not [e for e in y['events'] if e[0]=='delay_ms']
            assert sum(e[0]=='watchdog' for e in y['events'])==2
            assert [e[1] for e in y['events'] if e[0]=='printf']==['Orange State\n\n',"Your device has been unlocked and can't be trusted\n",'Your device will boot in 5 seconds\n']
        else:assert x==y
        assert x['return']==y['return'];cases.append({'state':state,'original':x,'patched':y})
    assert run(b,direct=True)==run(b,2) and run(q,direct=True)==run(q,2)
    rejected=0
    for bad in [b[:-1],b+b'\0',q,b[:100]+bytes([b[100]^1])+b[101:]]:
        try:patch(bad)
        except ValueError:rejected+=1
        else:raise AssertionError('Unpinned input accepted')
    report={'pass':True,'candidate_sha256':digest(q),'dispatcher_states':cases,'rejected_bad_inputs':rejected,'checks':['Exact four-byte replacement and no other differences','BL target and two NOP instruction widths','States0..4 keep dispatcher behavior','Orange only loses delay(5000), keeps3prints+2watchdog calls','Direct and dispatched paths match','Return value, SP, r4..r11 preserved, external-call SP8aligned'], 'limits':'Callees mocked; no timing, full boot, display, watchdog, authentication or phone execution proof'}
    a.report.write_text(json.dumps(report,indent=2)+'\n');print('PASS: five dispatch states, direct entry, ABI, exact diff, four rejected inputs')
if __name__=='__main__':main()
