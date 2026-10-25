#!/usr/bin/env python3
"""Offline tests against original DA2 BSS/getter/allocator instructions."""
import argparse,ast,json,struct
from types import SimpleNamespace
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM,CS_MODE_THUMB
from capstone.arm_const import ARM_OP_MEM,ARM_REG_PC
from reserve_heap import extract_original,reserve,wrap_patcher,OLD_BASE,NEW_BASE,HEAP_END,PROTECTED_SPANS,sha

def original_execution(data,base,exact_fit=False):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(0x40000000,0x400000);u.mem_write(0x40000000,data)
    u.mem_map(0x67fff000,0x1000);u.mem_map(0x70000000,0x10000)
    trace=b'\xa5'*256;u.mem_write(0x40084000,trace)
    writes=[]
    def on_write(uc,access,addr,size,value,unused):
        if not (0x40000000<=addr<0x40400000 or 0x67fff000<=addr<0x68000000 or 0x70000000<=addr<0x70010000):
            raise AssertionError('unexpected memory destination '+hex(addr))
        if 0x40084000<=addr<0x40084100:writes.append((addr,size,value))
    def on_code(uc,addr,size,unused):
        if addr in (0x4000ac18,0x4000ac30): # OS interrupt/critical-section entry/exit only
            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    u.hook_add(UC_HOOK_CODE,on_code);u.hook_add(UC_HOOK_MEM_WRITE,on_write)
    def call(addr,r0=0,r1=0):
        u.reg_write(UC_ARM_REG_SP,0x7000f000);u.reg_write(UC_ARM_REG_LR,0x70000001)
        u.reg_write(UC_ARM_REG_R0,r0);u.reg_write(UC_ARM_REG_R1,r1)
        u.emu_start(addr|1,0x70000000,count=10000)
        assert u.reg_read(UC_ARM_REG_PC)==0x70000000
        return u.reg_read(UC_ARM_REG_R0)
    # Execute original ARM BSS-clear loop only, stopping before FP/entry code.
    u.emu_start(0x400000d4,0x400000ec,count=100000)
    assert bytes(u.mem_read(0x40051090,0xd210))==b'\0'*0xd210
    assert bytes(u.mem_read(0x40084000,256))==trace
    assert call(0x4000a338)==HEAP_END-base
    call(0x4000add4)
    assert struct.unpack('<II',bytes(u.mem_read(0x400538a0,8)))==(base,HEAP_END-base)
    assert struct.unpack('<I',bytes(u.mem_read(base+8,4)))[0]==HEAP_END-base
    allocations=[]
    requested=[HEAP_END-base-12] if exact_fit else [100,0x100000,0x2000,0x100000]
    for size in requested:
        ptr=call(0x4000ae00,size)
        assert base<=ptr and ptr+size<=HEAP_END
        allocations.append({'start':hex(ptr),'bytes':size,'end_exclusive':hex(ptr+size),
                            'contains_trace':ptr<=0x40084000 and ptr+size>=0x40084100})
        if base==NEW_BASE:assert ptr>=0x40090000
    if exact_fit:assert call(0x4000ae00,4)==0
    assert bytes(u.mem_read(0x40084000,256))==trace and not writes
    return {'heap_base':hex(base),'heap_size':HEAP_END-base,'exact_fit':exact_fit,'allocations':allocations,
            'trace_writes_in_executed_snippets':0,'passed':True}

def literal_uses(data):
    references=[]
    targets={0x40000120,0x4000a340,0x4000a344,0x4000adf8}
    for mode,step in [(CS_MODE_ARM,4),(CS_MODE_THUMB,2)]:
        md=Cs(CS_ARCH_ARM,mode);md.detail=True
        for off in range(0,len(data)-4,step):
            for i in md.disasm(data[off:off+4],0x40000000+off,count=1):
                if i.mnemonic.startswith('ldr') and len(i.operands)>1 and i.operands[1].type==ARM_OP_MEM and i.operands[1].mem.base==ARM_REG_PC:
                    target=((i.address+(4 if mode==CS_MODE_THUMB else 8))&~3)+i.operands[1].mem.disp
                    if target in targets:references.append((i.address,target))
    expected=[(0x400000d8,0x40000120),(0x4000a338,0x4000a340),(0x4000a33a,0x4000a344),(0x4000add6,0x4000adf8)]
    assert sorted(references)==sorted(expected)
    offsets=[];needle=struct.pack('<I',OLD_BASE);pos=0
    while (pos:=data.find(needle,pos))!=-1:offsets.append(pos);pos+=1
    assert offsets==[0x120,0xa340,0xadf8]
    return {'old_base_word_occurrences':[hex(o) for o in offsets],
            'pc_relative_references':[{'instruction':hex(i),'literal':hex(t)} for i,t in references],
            'scope':'Every aligned ARM/Thumb single-instruction PC-relative LDR candidate in pinned region; not whole-program indirect dataflow proof.'}

def existing_patcher_check(root,loader,original):
    # Extract only three already-reviewed pure Python methods. Do not import
    # mtkclient's device modules, construct a client or create a transport.
    ns={};sources=[]
    for rel,cls,name in [
      ('mtkclient/Library/utils.py',None,'find_binary'),
      ('mtkclient/Library/mtk_class.py','Mtk','patch_preloader_security_da2'),
      ('mtkclient/Library/DA/xflash/extension/xflash.py','XFlashExt','patch_da2')]:
        path=root/rel;text=path.read_text();tree=ast.parse(text)
        parent=tree if cls is None else next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
        function=next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name)
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),ns)
        sources.append({'path':rel,'sha256':sha(path.read_bytes()),'method':name})
    logs=[];dummy=SimpleNamespace(info=logs.append,warning=logs.append)
    dummy.mtk=SimpleNamespace(patch_preloader_security_da2=lambda b:ns['patch_preloader_security_da2'](dummy,b))
    manifests=[]
    output=wrap_patcher(lambda b:ns['patch_da2'](dummy,b),loader,manifests.append)(original)
    assert manifests and all(output[o:o+4]==struct.pack('<I',NEW_BASE) for o in (0xa340,0xadf8))
    return {'passed':True,'reviewed_source_methods':sources,'patcher_messages':logs,'manifest':manifests[0],
            'scope':'Executed original pure methods with log collector; no client, module initialization or transport.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--loader',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--mtkclient',type=Path)
    a=p.parse_args();loader=a.loader.read_bytes();original=extract_original(loader)
    patched,manifest=reserve(original,original)
    refs=literal_uses(original)
    execution=[original_execution(data,base,fit) for data,base in [(original,OLD_BASE),(patched,NEW_BASE)] for fit in [False,True]]
    assert execution[0]['allocations'][1]['contains_trace']
    assert not any(v['contains_trace'] for e in execution[2:] for v in e['allocations'])
    rejected=[]
    for name,source,candidate in [
        ('wrong_original',original[:-1]+bytes([original[-1]^1]),original),
        ('truncated',original,original[:-0x100]),('already_reserved',original,patched)]:
        try:reserve(source,candidate)
        except ValueError:rejected.append(name)
        else:raise AssertionError(name+' accepted')
    for lo,hi in PROTECTED_SPANS:
        changed=bytearray(original);changed[lo]^=1
        try:reserve(original,changed)
        except ValueError:rejected.append('protected_span_'+hex(lo))
        else:raise AssertionError('modified protected span accepted')
    order=[];records=[]
    def prior(data):
        order.append('existing_patcher');out=bytearray(data);out[0x30000]^=1;return out
    def record(m):order.append('manifest');records.append(m)
    wrapped=wrap_patcher(prior,loader,record)
    result=wrapped(original)
    assert order==['existing_patcher','manifest'] and result[0x30000]==(original[0x30000]^1)
    assert records[0]['reserved_da2_sha256']==sha(result)
    report={'passed':True,'manifest':manifest,'reference_scan':refs,'original_code_execution':execution,
            'negative_cases_rejected':rejected,'wrapper_order':order,
            'scope':'Model OS critical sections only. Original getter, heap initialization, free-list allocation and BSS-clear code execute. No DA USB/DRAM/DMA path executes.',
            'retention_claim':'The reserved interval is excluded from this allocator only. Overall trace survival remains unproven.'}
    if a.mtkclient:report['existing_mtkclient_patcher']=existing_patcher_check(a.mtkclient,loader,original)
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':True,'allocator_runs':4,'negative_cases':len(rejected),'old_stack_contains_trace':True,'new_heap_excludes_trace':True}))
if __name__=='__main__':main()
