#!/usr/bin/env python3
"""Bind the capture26 charger entry fixture to all235 raw record entries."""
import hashlib
import json
from pathlib import Path
import struct

HERE=Path(__file__).resolve().parent
PORT=HERE.parents[4]
BSP=Path('/mnt/0da18f53-c547-40a2-a7c3-b08e84d1aab4/alps/aosp-docker/workspace')
CAPTURE=PORT/'hardware/trace-boot-20261025/capture26'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    raw_path=CAPTURE/'peripherals.bin'
    decoded_path=CAPTURE/'peripherals-result.json'
    manifest_path=PORT/'boot/physical-xnu-build33/physical-manifest.json'
    catalog_path=CAPTURE.parent/'peripheral-registers-v3.json'
    raw=raw_path.read_bytes();decoded=json.loads(decoded_path.read_text())
    manifest=json.loads(manifest_path.read_text())
    catalog=json.loads(catalog_path.read_text())['registers']
    assert len(raw)==4096 and raw[:16]==struct.pack('<8sII',b'MTKPER01',2,4096)
    assert raw[16:48]==bytes.fromhex(manifest['trace']['identity'])
    assert struct.unpack_from('<4I',raw,48)==(2,0xfffffffd,2,234)
    assert digest(raw_path)==decoded['sha256'] and len(decoded['registers'])==len(catalog)==235
    observed={}
    for i,(e,c) in enumerate(zip(decoded['registers'],catalog)):
        actual=struct.unpack_from('<IBBHII',raw,96+i*16)
        expected=(int(e['address'],0),e['width'],e['group'],e['valid'],e['first'],e['second'])
        assert actual==expected and actual[:3]==(int(c['address'],0),c['width'],c['group'])
        assert actual[0] not in observed and actual[3]==3
        observed[actual[0]]=e
    assert not any(raw[96+235*16:])
    old=json.loads((HERE/'i2c5-handoff-passive-review.json').read_text())
    addresses={int(e['address'],0) for e in old['new_passive_registers']}
    assert len(addresses)==36
    addresses|={0x100000a0,0x10001090,0x10001094,0x100010c8,
                0x1000c26c,0x1000c270,0x1000c278,0x100026c0,0x0c000000}
    entries=[observed[a] for a in sorted(addresses)]
    assert len(entries)==45
    source_paths=[raw_path,decoded_path,manifest_path,catalog_path,
        CAPTURE/'xnu-log.bin',HERE/'i2c5-handoff-passive-review.json',
        BSP/'kernel-4.14/drivers/pinctrl/mediatek/pinctrl-mt6765.c',
        BSP/'kernel-4.14/include/dt-bindings/pinctrl/mt6765-pinfunc.h',
        BSP/'kernel-4.14/drivers/clk/mediatek/clk-mt6765.c',
        BSP/'kernel-4.14/drivers/i2c/busses/i2c-mtk.h',
        BSP/'kernel-4.14/drivers/i2c/busses/i2c-mtk.c']
    output={'format':'mt6762-charger-entry-capture26-1','offline_only':True,
        'source_hashes':{str(p):digest(p) for p in source_paths},
        'raw_record_version':2,'frozen_catalog_name':catalog_path.name,
        'image_identity':raw[16:48].hex(),'all235_records_checked':True,
        'registers':entries,
        'scope':'Pre-XNU inherited entry only; no bus5 setup or charger transaction observed.',
        'gpio_din_variation':{'xor':hex(observed[0x10005210]['first']^observed[0x10005210]['second']),
            'scl_sda_mask':'0x30000','both_passes_high':all(observed[0x10005210][p]&0x30000==0x30000 for p in ('first','second'))},
        'pending_irq':'INTID162 is pending but disabled and inactive; entry checker does not read/acknowledge pending.',
        'unresolved':['No post-write I2C5 DIV/HS/IO/TIMING/TIMEOUT readback yet.',
                      'Entry readbacks do not establish PSC5425E identity, charger policy ownership or analog safety.',
                      'Entry read-only profile does not grant access to display-bias address0x3e.']}
    (HERE/'physical-charger-entry-capture26.json').write_text(json.dumps(output,indent=2)+'\n')
    print('PASS:235 raw/catalog/decoded entries verified;45 charger/shared fixture fields saved; no phone access')

if __name__=='__main__':main()
