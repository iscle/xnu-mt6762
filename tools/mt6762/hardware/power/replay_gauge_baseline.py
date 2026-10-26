"""Replay exact stock ARM64 coefficient initialization offline; no device I/O.

Only the named initialization blocks and complete scalar multiplication helper
execute. OF scalar reads, profiling and debug level are mocked; this is not a
whole stock boot. Also retain bounded disassembly of runtime coefficient paths.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_W0,UC_ARM64_REG_X1
from unicorn.arm64_const import UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_X4
from unicorn.arm64_const import UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X27

HERE=Path(__file__).resolve().parent
PORT=HERE.parents[4]
BASE=0xffffff8008080000
IMAGE_SHA='82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
BLOCKS=[('constructor',0xffffff8008a86678,0xffffff8008a86694),
    ('header_coefficients',0xffffff8008a7c488,0xffffff8008a7c4a8),
    ('dt_car_tune',0xffffff8008a7cca4,0xffffff8008a7cce0),
    ('dt_r_fg',0xffffff8008a7cd2c,0xffffff8008a7cd6c)]
HELPER=(0xffffff8008a7e168,0xffffff8008a7e21c)
OF_READ=0xffffff8008b39dec
PROFILE_CALLS=(0xffffff800809ef9c,0xffffff8008a7b010)

class Baseline(C.Structure):
    _fields_=[(name,C.c_uint32) for name in ['version','fdt_size','dt_r_fg','dt_car_tune','r_fg','car_tune']]

def sha(data):return hashlib.sha256(data).hexdigest()

def replay(image,values):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);uc.mem_map(BASE,0x2000000);uc.mem_write(BASE,image)
    uc.mem_map(0x100000,0x10000);uc.mem_map(0x300000,0x40000)
    gm=0x300000;gauge=0x320000
    uc.mem_write(gm+0x1f8,struct.pack('<Q',gauge));uc.reg_write(UC_ARM64_REG_SP,0x10f000)
    calls=[];writes=[]
    def write_hook(u,access,address,size,value,_):
        if address<gauge+0x118 and address+size>gauge+0x110:
            writes.append(dict(pc=f'{u.reg_read(UC_ARM64_REG_PC):016x}',
                gauge_offset=hex(address-gauge),size=size,value=f'{value:x}'))
    def code_hook(u,address,size,_):
        if address in PROFILE_CALLS:
            u.reg_write(UC_ARM64_REG_X0,0);u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        elif address==OF_READ:
            name=bytes(u.mem_read(u.reg_read(UC_ARM64_REG_X1),80)).split(b'\0')[0].decode()
            assert name in ('R_FG_VALUE','CAR_TUNE_VALUE')
            assert u.reg_read(UC_ARM64_REG_X3)==1 and u.reg_read(UC_ARM64_REG_X4)==0
            calls.append(dict(property=name,present=name in values))
            if name in values:
                u.mem_write(u.reg_read(UC_ARM64_REG_X2),struct.pack('<I',values[name]))
                u.reg_write(UC_ARM64_REG_W0,1)
            else:u.reg_write(UC_ARM64_REG_W0,0xffffffea)
            u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        elif not any(start<=address<end for start,end in
                     [(start,end) for _,start,end in BLOCKS]+[HELPER]):
            raise RuntimeError(f'unexpected original-code execution {address:x}')
    uc.hook_add(UC_HOOK_CODE,code_hook);uc.hook_add(UC_HOOK_MEM_WRITE,write_hook)
    uc.reg_write(UC_ARM64_REG_X20,gauge);uc.reg_write(UC_ARM64_REG_X19,0x330000)
    uc.emu_start(BLOCKS[0][1],BLOCKS[0][2],count=2048)
    assert uc.reg_read(UC_ARM64_REG_PC)==BLOCKS[0][2]
    initial=struct.unpack('<II',uc.mem_read(gauge+0x110,8));assert initial==(50,1000)
    uc.reg_write(UC_ARM64_REG_X19,gm)
    uc.emu_start(BLOCKS[1][1],BLOCKS[1][2],count=2048)
    assert uc.reg_read(UC_ARM64_REG_PC)==BLOCKS[1][2]
    for _,start,end in BLOCKS[2:]:
        uc.reg_write(UC_ARM64_REG_X27,gm);uc.reg_write(UC_ARM64_REG_X20,0x330000)
        uc.emu_start(start,end,count=2048);assert uc.reg_read(UC_ARM64_REG_PC)==end
    result=struct.unpack('<II',uc.mem_read(gauge+0x110,8))
    expected=(values.get('R_FG_VALUE',5)*10,values.get('CAR_TUNE_VALUE',100)*10)
    assert result==expected
    return dict(properties=values,constructor_pair=list(initial),initialized_pair=list(result),
                of_read_calls=calls,active_field_writes=writes)

def direct_setters(image):
    md=Cs(CS_ARCH_ARM64,CS_MODE_ARM);calls=[];dt_calls=[]
    for offset in range(0,len(image)-3,4):
        word=struct.unpack_from('<I',image,offset)[0]
        if word&0x7c000000!=0x14000000:continue
        immediate=word&0x3ffffff
        if immediate&0x2000000:immediate-=0x4000000
        address=BASE+offset;target=address+4*immediate
        if target==0xffffff8008a7caec:dt_calls.append(f'{address:016x}')
        if target!=0xffffff8008a7c2b0:continue
        prop=None
        for _,_,mnemonic,operands in reversed(list(md.disasm_lite(image[offset-64:offset],address-64))):
            if mnemonic=='bl':break
            if mnemonic=='mov' and operands.startswith('w0, #'):
                prop=int(operands.split('#')[1],0);break
        calls.append(dict(address=f'{address:016x}',property=prop))
    assert len(calls)==88 and all(row['property'] is not None for row in calls)
    assert not any(row['property']==0x33 for row in calls)
    assert dt_calls==['ffffff8008a800b8']
    return dict(dt_initializer_calls=dt_calls,gauge_set_property_calls=calls,
        scope='Direct B/BL inventory of the exact Image; sysfs callbacks remain indirect runtime writers')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,default=PORT/'firmware/Image')
    parser.add_argument('--dtb',type=Path,action='append')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--disassembly-output',type=Path)
    args=parser.parse_args();image=args.image.read_bytes()
    if sha(image)!=IMAGE_SHA:raise SystemExit('Refusing a different stock Image')
    sources=args.dtb or [PORT/'firmware/boot.bin.dtb',PORT/'hardware/trace-boot-20261025/capture30/runtime.dtb']
    physical=[]
    with tempfile.TemporaryDirectory() as temporary:
        library=Path(temporary)/'baseline.so'
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-ffreestanding','-shared','-fPIC',
            str(HERE/'mt6762_gauge_baseline.c'),'-o',str(library)],check=True)
        query=C.CDLL(str(library)).mt6762_gauge_baseline_from_fdt
        query.argtypes=[C.c_void_p,C.c_size_t,C.POINTER(Baseline)];query.restype=C.c_int
        for path in sources:
            data=path.read_bytes();buffer=C.create_string_buffer(data);baseline=Baseline()
            if query(buffer,len(data),C.byref(baseline)):raise SystemExit(f'Refusing DT profile: {path}')
            result=replay(image,dict(R_FG_VALUE=baseline.dt_r_fg,CAR_TUNE_VALUE=baseline.dt_car_tune))
            assert result['initialized_pair']==[baseline.r_fg,baseline.car_tune]==[100,1000]
            physical.append(dict(path=str(path),sha256=sha(data),fdt_size=baseline.fdt_size,replay=result))
    fixtures=[replay(image,values) for values in [{},{'R_FG_VALUE':10},{'CAR_TUNE_VALUE':100},
        {'R_FG_VALUE':11,'CAR_TUNE_VALUE':101}]]
    ranges=BLOCKS+[('scalar_reader',*HELPER),
        ('info_set',0xffffff8008a85694,0xffffff8008a85730),
        ('calibration_result_store',0xffffff8008a85930,0xffffff8008a85960),
        ('info_get',0xffffff8008a85cd8,0xffffff8008a85da8),
        ('factory_ioctl_gm_writes',0xffffff8008a888dc,0xffffff8008a88948),
        ('engineering_gm_r_fg',0xffffff8008a89a08,0xffffff8008a89a28),
        ('engineering_gm_tune',0xffffff8008a8a164,0xffffff8008a8a18c)]
    md=Cs(CS_ARCH_ARM64,CS_MODE_ARM);disassembly=[]
    for name,start,end in ranges:
        disassembly.append(f'\n{name} [{start:016x},{end:016x})\n')
        for address,_,mnemonic,operands in md.disasm_lite(image[start-BASE:end-BASE],start):
            disassembly.append(f'{address:016x}: {mnemonic:8} {operands}'.rstrip()+'\n')
    disassembly=''.join(disassembly)
    result=dict(schema='mt6762-stock-gauge-baseline-replay-v1',image_sha256=IMAGE_SHA,
        scope=__doc__,physical_hardware_tested=False,historical_runtime_value_recovered=False,
        source_sha256={name:sha((HERE/name).read_bytes()) for name in
            ['mt6762_gauge_baseline.c','mt6762_gauge_baseline.h','replay_gauge_baseline.py']},
        physical_dt_inputs=physical,branch_fixtures=fixtures,direct_call_inventory=direct_setters(image),
        disassembly_sha256=sha(disassembly.encode()))
    if args.disassembly_output:args.disassembly_output.write_text(disassembly)
    text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    else:print(text,end='')

if __name__=='__main__':main()
