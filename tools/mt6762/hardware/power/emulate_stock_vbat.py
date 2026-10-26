"""Run exact shipped ADC request/conversion code with mocked MMIO, offline."""
from pathlib import Path
import hashlib
import json
import struct
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_W0

HERE=Path(__file__).resolve().parent
PORT=HERE.parents[3].parents[2]
IMAGE=PORT/'firmware/Image'
BLOB=IMAGE.read_bytes();BASE=0xffffff8008080000
DIGEST=hashlib.sha256(BLOB).hexdigest()
assert DIGEST=='82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
DESC=0xffffff80098932c8+64
TABLE=0xffffff8009105ef8+12
assert struct.unpack_from('<III',BLOB,TABLE-BASE)==(0x110e,1,0x108a)
assert BLOB[DESC-BASE+0x19]==15
assert struct.unpack_from('<QQ',BLOB,DESC-BASE+0x30)==(0,0)

def run(raw):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(BASE,0x2000000);u.mem_write(BASE,BLOB)
    u.mem_map(0x100000,0x10000);u.mem_map(0x200000,0x10000);u.mem_map(0x300000,0x10000)
    u.reg_write(UC_ARM64_REG_SP,0x10f000);u.reg_write(UC_ARM64_REG_LR,0x200000)
    # Exact DT-supplied resistance ratio and averaging; original immutable
    # descriptor supplies resolution. Original reg table supplies target.
    u.mem_write(DESC+0x1a,bytes([3,1])+struct.pack('<H',128))
    u.mem_write(DESC+0x20,struct.pack('<Q',TABLE))
    u.mem_write(0x3005c8,struct.pack('<Q',0x305000))
    u.mem_write(0x302004,struct.pack('<I',1))
    for reg,value in [(UC_ARM64_REG_X0,0x300000),(UC_ARM64_REG_X1,0x302000),
                      (UC_ARM64_REG_X2,0x303000),(UC_ARM64_REG_X3,0x303004),(UC_ARM64_REG_X4,1)]:u.reg_write(reg,value)
    requests=[];reads=[];sleeps=[];clock=[1000000]
    def ret(value=0):
        u.reg_write(UC_ARM64_REG_W0,value&0xffffffff);u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
    def hook(_,address,size,context):
        del size,context
        if address in [0xffffff800809ef9c,0xffffff8008f2e614,0xffffff8008f2e684,
                       0xffffff800864e458,0xffffff800864e618,0xffffff8008f22cdc]:ret();return
        if address==0xffffff8008656d84:
            reg,value=u.reg_read(UC_ARM64_REG_X1),u.reg_read(UC_ARM64_REG_X2)
            assert (reg,value)==(0x110e,2);requests.append([reg,value]);ret();return
        if address==0xffffff800865809c:
            reg=u.reg_read(UC_ARM64_REG_X1);assert reg==0x108a
            reads.append(reg);u.mem_write(u.reg_read(UC_ARM64_REG_X2),struct.pack('<I',0x8000|raw));ret();return
        if address==0xffffff8008f31324:
            lo,hi=u.reg_read(UC_ARM64_REG_X0),u.reg_read(UC_ARM64_REG_X1)
            assert (lo,hi)==(1280,1290);sleeps.append([lo,hi]);clock[0]+=lo*1000;ret();return
        if address==0xffffff800814accc:
            u.reg_write(UC_ARM64_REG_X0,clock[0]);u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR));return
        if not (0xffffff8008b6aab8<=address<0xffffff8008b6ac64 or 0xffffff8008b6b8fc<=address<0xffffff8008b6badc):
            raise RuntimeError(f'unexpected original PC {address:x}')
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0xffffff8008b6b8fc,0x200000,count=3000)
    assert u.reg_read(UC_ARM64_REG_PC)==0x200000 and u.reg_read(UC_ARM64_REG_W0)==1
    value=struct.unpack('<i',u.mem_read(0x303000,4))[0]
    assert requests==[[0x110e,2]] and reads==[0x108a] and sleeps==[[1280,1290]]
    assert value==(raw*3*1800)>>15
    return {'raw':raw,'millivolts':value,'requests':requests,'reads':reads,'sleep_ranges_us':sleeps}

if __name__=='__main__':
    result={'schema':'mt6762-original-vbat-replay-v1','image_sha256':DIGEST,
        'method':'Unmodified mt635x_auxadc_read_raw and get_auxadc_out ARM64; DT ratio/avg and exact static register descriptor; mocked locks/regmap/time/logging.',
        'physical_hardware_tested':False,'readiness_transition_proven':False,
        'boundary':'Original stock waits then accepts ready-high. Native observer additionally requires post-request ready-low and rejects rails/late results.',
        'descriptor_resolution':15,'conversion_callback':0,'calibration_callback':0,
        'cases':[run(raw) for raw in [0,1,6,10000,20000,25000,28000,32766,32767]]}
    output=HERE/'evidence/stock-vbat-vectors.json';output.write_text(json.dumps(result,indent=2)+'\n')
    print(f'PASS: {len(result["cases"])} original ARM64 VBAT request/processed conversions; no hardware I/O')
