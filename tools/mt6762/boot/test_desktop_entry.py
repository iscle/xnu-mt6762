#!/usr/bin/env python3
"""Offline Mach-O startup regression: original stack retained and C SP aligned.
Unicorn executes startup instructions; explicit checks enforce the architectural
SP invariant because this is not a physical Cortex-A53 exception test.
"""
import argparse,hashlib,json,struct
from pathlib import Path
def main():
    import capstone
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_SP,UC_ARM64_REG_X0,UC_ARM64_REG_X16,UC_ARM64_REG_PC
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    binary=args.artifact.resolve();blob=binary.read_bytes()
    header=struct.unpack_from('<8I',blob);assert header[:4]==(0xfeedfacf,0x100000c,0,2)
    offset=32;segments=[];symbols={};entry=None
    for _ in range(header[4]):
     cmd,size=struct.unpack_from('<II',blob,offset)
     if cmd==0x19:
      name=blob[offset+8:offset+24].rstrip(b'\0').decode()
      vm,vs,fo,fs=struct.unpack_from('<4Q',blob,offset+24)
      if vm and vs:segments.append((name,vm,vs,fo,fs))
     elif cmd==5:
      assert struct.unpack_from('<II',blob,offset+8)==(6,68)
      regs=struct.unpack_from('<33Q',blob,offset+16);entry=regs[32]
     elif cmd==2:
      sy,n,st,ss=struct.unpack_from('<4I',blob,offset+8)
      for i in range(n):
       si,ty,se,de,value=struct.unpack_from('<IBBHQ',blob,sy+16*i)
       end=blob.find(b'\0',st+si);symbols[blob[st+si:end].decode()]=value
     offset+=size
    assert entry==symbols['_start'];main=symbols['_desktop_main']
    md=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_ARM);md.detail=True
    def bytes_at(address,count):
     for _,vm,vs,fo,fs in segments:
      if vm<=address<vm+fs:return blob[fo+address-vm:fo+address-vm+count]
     raise ValueError(hex(address))
    wrapper=list(md.disasm(bytes_at(entry,16),entry))
    assert len(wrapper)==4 and [x.mnemonic for x in wrapper]==['mov','and','mov','b']
    assert wrapper[-1].operands[0].imm==main
    cases=[]
    for original_sp in [0x16fdffe80+i for i in range(16)]+[0x16fdffd00,0x16fdffd08]:
     uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
     for _,vm,vs,fo,fs in segments:
      uc.mem_map(vm,vs)
      if fs:uc.mem_write(vm,blob[fo:fo+fs])
     uc.mem_map(0x16fdf0000,0x10000)
     initial=bytes(range(128));uc.mem_write(original_sp,initial)
     uc.reg_write(UC_ARM64_REG_SP,original_sp)
     reached=[];stack_accesses=[]
     def hook(machine,address,size,unused):
      instruction=next(md.disasm(bytes(machine.mem_read(address,size)),address))
      if address==main:
       assert machine.reg_read(UC_ARM64_REG_X0)==original_sp
       assert machine.reg_read(UC_ARM64_REG_SP)==original_sp&~15
       reached.append('C entry')
      for operand in instruction.operands:
       if operand.type==capstone.arm64.ARM64_OP_MEM and operand.mem.base==capstone.arm64.ARM64_REG_SP:
        assert machine.reg_read(UC_ARM64_REG_SP)%16==0
        stack_accesses.append(hex(address))
      if instruction.mnemonic=='svc':
       assert reached==['C entry'] and machine.reg_read(UC_ARM64_REG_X16)==5
       text=bytes(machine.mem_read(machine.reg_read(UC_ARM64_REG_X0),13))
       assert text==b'/dev/console\0'
       reached.append('open console syscall');machine.emu_stop()
     uc.hook_add(UC_HOOK_CODE,hook)
     uc.emu_start(entry,0,count=200)
     assert reached==['C entry','open console syscall']
     assert bytes(uc.mem_read(original_sp,len(initial)))==initial
     cases.append(dict(original_sp=hex(original_sp),c_entry_sp=hex(original_sp&~15),
                       original_stack_argument_preserved=True,original_stack_bytes_unchanged=True,
                       checked_stack_accesses=stack_accesses,first_syscall_pc=hex(uc.reg_read(UC_ARM64_REG_PC))))
    report=dict(result='PASS',artifact=str(binary),artifact_sha256=hashlib.sha256(blob).hexdigest(),
     entry=hex(entry),c_entry=hex(main),entry_disassembly=[f'{i.address:#x}: {i.mnemonic} {i.op_str}' for i in wrapper],
     cases=cases,scope='Original new Mach-O startup instructions executed offline through first console-open syscall; explicit SP checks; no kernel/phone execution or syscall implementation',
     script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if args.output:
     args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2));print('cases',len(cases))


if __name__ == "__main__":
    main()
