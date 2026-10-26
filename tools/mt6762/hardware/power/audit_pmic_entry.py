"""Pin the passive observer's register sources and existing physical coverage.

Offline only: reads saved BSP, disassembly and captures; never opens a device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bsp',type=Path,default=Path('/mnt/0da18f53-c547-40a2-a7c3-b08e84d1aab4/alps/aosp-docker/workspace'))
parser.add_argument('--port',type=Path,default=HERE.parents[4])
parser.add_argument('--output',type=Path)
args=parser.parse_args()
registers=args.bsp/'kernel-4.14/include/linux/mfd/mt6357/registers.h'
source=registers.read_text()
rows=[
    ('HWCID',0x0008),('BM_TOP_CKPDN_CON0',0x0c0c),('FGADC_CON0',0x0d08),
    ('FGADC_CON1',0x0d0a),('FGADC_ANA_ELR0',0x0c8e),('FGADC_ANA_ELR1',0x0c90),
    ('FGADC_OFFSET_CON1',0x0d94),('FGADC_GAIN_CON0',0x0d96),
    ('BATON_ANA_CON0',0x0e08),('AUXADC_ADC1',0x108a),('AUXADC_ADC3',0x108e),
    ('AUXADC_ADC11',0x109e),('AUXADC_CHR_TOP_CON2',0x1236)]
catalog=[]
for label,address in rows:
    expression=r'^#define MT6357_'+label+r'\s+\(MT6357_PMIC_REG_BASE\+0x([0-9a-f]+)\)'
    match=re.search(expression,source,re.M)
    if not match or int(match[1],16)!=address:
        raise SystemExit(f'BSP register mismatch: {label} {address:#x}')
    catalog.append(dict(address=f'{address:04x}',width=2,label=label,
                        source_line=source.count('\n',0,match.start())+1))

def identity(path):
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

captures=[]
for number in (26,27):
    path=args.port/f'hardware/trace-boot-20261025/capture{number}/xnu-log.bin'
    log=path.read_bytes()
    observations={}
    for match in re.finditer(rb'MT6762_PWRAP_SAMPLE pass=(\d+) address=([0-9a-f]+) error=(-?\d+) value=([0-9a-f]+)',log):
        key=(int(match[1]),match[2].decode(),int(match[3]),match[4].decode())
        observations[key]=dict(pass_index=key[0],address=key[1],error=key[2],value=key[3])
    if not observations:
        raise SystemExit(f'No PMIC samples in capture{number}')
    seen={int(row['address'],16) for row in observations.values()}
    captures.append(dict(number=number,**identity(path),
        samples_deduplicated=list(observations.values()),
        missing_observer_addresses=[f'{address:04x}' for _,address in rows if address not in seen],
        pmic_identification_logged=bool(re.search(rb'MT6762_PWRAP_READY profile=\d+ id=5730 read_only=1',log))))

evidence_files=['gauge-protocol-disassembly.txt','gauge-init-disassembly.txt',
    'gauge-sysfs-coefficients.json','battery-presence-disassembly.txt',
    'ntc-compensation-bif-disassembly.txt']
result=dict(schema='mt6762-pmic-entry-source-audit-v1',
    stock_image_sha256='82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b',
    provenance=[identity(registers),identity(args.bsp/'kernel-4.14/drivers/iio/adc/mt635x-auxadc.c')]+
        [identity(HERE/'evidence'/name) for name in evidence_files],
    register_catalog=catalog,captures=captures,
    implemented_scope=dict(passes=2,maximum_read_transactions=26,pmic_write_transactions=0,
        atomic_measurements=False,adc_freshness_established=False,calibration_granted=False,
        ownership_granted=False,charging_policy_enabled=False),
    unresolved=['physical observer execution/readbacks',
        'active R_FG/CAR_TUNE software coefficients at the next gauge handoff',
        'exclusive gauge latch and ADC channel ownership',
        'fresh coherent current/CAR and fresh ADC conversion admission',
        'NTC/BIF compensation and safe restoration/control ownership',
        'PSC identity, CE-disable/readback and charging policy'])
text=json.dumps(result,indent=2)+'\n'
if args.output:args.output.write_text(text)
else:print(text,end='')
