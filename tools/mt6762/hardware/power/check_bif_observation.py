#!/usr/bin/env python3
"""Check native raw BIF diagnostic records against the explicit QEMU fixture.
No device access and no calibrated-temperature inference.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


def check(serial, report, post_trim=False):
    rows=re.findall(r'MT6762_BIF_OBSERVATION error=(-?\d+) size=(\d+) data=([0-9a-f]*)',serial)
    if not rows:
        raise ValueError('No native complete-record observations')
    expected=(0x4000,0,0,0,0,0,0,0,0,0,0x1357,0x2468,0x369c,0x48ad,0x5bce,0x6df0,0x7e12)
    valid=[];invalid=0;failed_after_fresh=False
    for error,size,hexdata in rows:
        if int(size)!=72:
            raise ValueError('Wrong native record size')
        if int(error):
            if int(error)!=-6 or hexdata:
                raise ValueError('Unexpected failed read or partial error payload')
            invalid+=1
            if valid:failed_after_fresh=True
            continue
        if failed_after_fresh and post_trim:
            raise ValueError('Faulted snapshot became valid again')
        fields=struct.unpack('<IIQQ5H17H2H',bytes.fromhex(hexdata))
        version,size,acquired,expires=fields[:4]
        if version!=1 or size!=72 or expires-acquired!=26000000:
            raise ValueError('Invalid version, size, or 2-second 13MHz acquisition lease')
        if fields[4:9]!=(0x5730,0x101,4,1400,4089) or fields[9:26]!=expected or fields[26:]!=(0,0):
            raise ValueError('Native raw record differs from the explicit fixture')
        if valid and acquired<valid[-1][0]:
            raise ValueError('Acquisition regressed')
        valid.append((acquired,expires))
    model=report['synthetic_power_state']
    if model['bif_tdet_write_attempts'] or model['bif_trim_write_attempts']:
        raise ValueError('Unexpected TDET or trim write')
    if model['bif_trim_reads']<21 or not valid:
        raise ValueError('Missing independent model reads or successful native snapshot')
    if post_trim:
        if not report['bif_fault_injected_after_fresh'] or not failed_after_fresh or int(rows[-1][0])!=-6:
            raise ValueError('No verified fresh-to-invalid trim transition')
    elif len(set(valid))<2 or int(rows[-1][0]):
        raise ValueError('Positive run did not sustain multiple acquisitions')
    return {'passed':True,'fresh_records':len(valid),'unavailable_records':invalid,
        'distinct_acquisitions':len(set(valid)),'post_fresh_trim_change':post_trim,
        'model_trim_reads':model['bif_trim_reads'],'tdet_writes':0,'trim_writes':0,
        'calibrated_temperature_proven':False,'physical_hardware_tested':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('serial',type=Path);p.add_argument('report',type=Path)
    p.add_argument('--post-trim',action='store_true');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.serial.read_bytes();report=a.report.read_bytes()
    result=check(raw.decode(errors='replace'),json.loads(report),a.post_trim)
    result.update(serial_sha256=hashlib.sha256(raw).hexdigest(),report_sha256=hashlib.sha256(report).hexdigest())
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))


if __name__=='__main__':main()
