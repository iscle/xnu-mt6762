"""Bind capture31 bus5 setup readbacks to retained Image37/kernel52 evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct

HERE=Path(__file__).resolve().parent
PORT=HERE.parents[4]
CAPTURE=PORT/'hardware/trace-boot-20261025/capture31'
MANIFEST=PORT/'boot/physical-xnu-build37/physical-manifest.json'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest=json.loads(MANIFEST.read_text());retained=json.loads((CAPTURE/'xnu-retained.json').read_text())
    log=(CAPTURE/'xnu-log.bin').read_bytes();peripherals=(CAPTURE/'peripherals.bin').read_bytes()
    decoded=json.loads((CAPTURE/'peripherals-result.json').read_text())
    assert digest(CAPTURE/'xnu-log.bin')==retained['log_sha256']=='28cb13c7522898d16074bf766a69178e5d0515d9f4272361b51562379adf9135'
    assert len(log)==retained['log_length']==110808
    assert retained['kernel_sha256']==manifest['kernel_sha256']=='b2999d92505ce79238a202ff965066236f97664bec3ddc08e886237e0ddb63e9'
    assert manifest['source_inputs_stable'] and manifest['native_charger_setup_probe_requested']
    assert not manifest['charger_transactions_granted'] and not manifest['charger_control_granted']
    module_path=HERE.parents[1]/'physical/trace_record.py'
    spec=importlib.util.spec_from_file_location('charger_trace31',module_path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    trace=module.decode((CAPTURE/'trace.bin').read_bytes(),bytes.fromhex(manifest['trace']['identity']))
    assert trace['phase']==10 and trace['executed']
    assert len(peripherals)==4096 and peripherals[:16]==struct.pack('<8sII',b'MTKPER01',2,4096)
    assert peripherals[16:48].hex()==trace['identity']
    assert digest(CAPTURE/'peripherals.bin')==decoded['sha256'] and len(decoded['registers'])==235
    assert struct.unpack_from('<4I',peripherals,48)==(2,0xfffffffd,2,234)
    for index,row in enumerate(decoded['registers']):
        assert struct.unpack_from('<IBBHII',peripherals,96+index*16)==(
            int(row['address'],0),row['width'],row['group'],3,row['first'],row['second'])
    def one(pattern):
        found=set(re.findall(pattern,log));assert len(found)==1,(pattern,found)
        return tuple(int(value,16) for value in next(iter(found)))
    setup=one(rb'MT6762_I2C_SETUP bus=5 div=([0-9a-f]+)/([0-9a-f]+) timing=([0-9a-f]+)/([0-9a-f]+) ltiming=([0-9a-f]+)/([0-9a-f]+) hs=([0-9a-f]+)/0 io=([0-9a-f]+)/3 clocks=([0-9a-f]+)')
    assert setup==(4,0x404,0x419,0x419,0x118,0x118,0x8000,3,1)
    aux=one(rb'MT6762_I2C_SETUP_AUX bus=5 ext=([0-9a-f]+)/([0-9a-f]+) delay=([0-9a-f]+)/a timeout=([0-9a-f]+)/([0-9a-f]+) top=([0-9a-f]+) infra0=([0-9a-f]+) infra1=([0-9a-f]+)')
    assert aux==(0x8001,0x8001,0xa,0x190,0x190,0x1030202,0,0)
    gates=one(rb'MT6762_I2C_SETUP_GATES bus=5 infra4=([0-9a-f]+) mask=([0-9a-f]+) setup_only=([0-9a-f]+)')
    assert gates==(0,0x1c0000,1)
    assert b'MT6762_I2C_SETUP_PROFILE bus=5 inherited=0' in log
    assert b'MT6762_I2C_SETUP_ONLY bus=5 strict=0 transactions=0' in log
    assert b'MT6762_I2C_READY bus=5' not in log and b'MT6762_PSC_PROBE' not in log
    programmed=dict(div=setup[1],timing=setup[3],ltiming=setup[5],hs=0,io=3,
        ext=aux[1],delay=0xa,timeout=aux[4])
    actual=dict(div=setup[0],timing=setup[2],ltiming=setup[4],hs=setup[6],io=setup[7],
        ext=aux[0],delay=aux[2],timeout=aux[3])
    paths=[MANIFEST,CAPTURE/'trace.bin',CAPTURE/'trace-result.json',CAPTURE/'xnu-retained.json',
        CAPTURE/'xnu-log.bin',CAPTURE/'peripherals.bin',CAPTURE/'peripherals-result.json']
    result=dict(schema='mt6762-charger-postsetup-capture31-v1',offline_only=True,
        source_sha256={str(path):digest(path) for path in paths},image_identity=trace['identity'],
        kernel_sha256=retained['kernel_sha256'],programmed=programmed,actual=actual,
        clocks=dict(stable=bool(setup[8]),top=aux[5],infra0=aux[6],infra1=aux[7],infra4=gates[0],dedicated_mask=gates[1]),
        scope='Actual XNU bus5 post-write readbacks. Peripheral record is earlier inherited entry, not post-write data.',
        observed_setup_only=True,observed_transactions=0,observed_psc_identity=False,
        limitations=['Retained cache may be incomplete; raw trace alone records entry, while retained XNU logs show setup execution.',
            'Readbacks do not establish PSC identity, charge-control ownership, CE-disable or an electrical safety fallback.',
            'Neither bus0 measurements nor bus5 pre-XNU entry values substitute for these post-write fields.'])
    (HERE/'physical-charger-postsetup-capture31.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: capture31 Image37/kernel52 linkage,235 raw records,and eight actual bus5 post-write words; no device access')

if __name__=='__main__':main()
