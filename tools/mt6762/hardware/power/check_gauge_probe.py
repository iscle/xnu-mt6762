#!/usr/bin/env python3
"""Check read-only native gauge observations from the original Apple IOKit probe.

Separate sysctl calls are not an atomic public snapshot. Require repeated
coherent observations on each side of a fault; preserve transition records.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def check(path, current_ua, charge_uah, require_fault):
    data=path.read_bytes(); text=data.decode(errors='replace').replace('\r','')
    records=[]
    absent=('CurrentCapacity','MaxCapacity','AppleRawCurrentCapacity',
            'AppleRawMaxCapacity','DesignCapacity','NominalChargeCapacity',
            'Temperature','CycleCount','TimeRemaining')
    for chunk in text.split('MT6762_BAT_PROBE ')[1:]:
        header=re.match(r'iteration=(\d+) readonly=1 status=0 ',chunk)
        if not header:continue
        fields={k:(int(v),int(e)) for k,v,e in re.findall(
            r'MT6762_BAT_SYSCTL (\w+)=(-?\d+) error=(\d+)',chunk)}
        properties=dict(re.findall(r'MT6762_BAT_PROPERTY (\w+)=(\S+)',chunk))
        if not fields or 'MT6762ValidFields' not in properties:continue
        assert all(properties.get(k)=='<absent>' for k in absent), 'unknown battery property published'
        def value(k):
            pair=fields.get(k)
            return pair[0] if pair and pair[1]==0 else None
        current=value('mt6762_gauge_current_ua'); charge=value('mt6762_gauge_charge_uah')
        cv=value('mt6762_gauge_current_valid');qv=value('mt6762_gauge_charge_valid')
        fresh=(current,charge,cv,qv)==(current_ua,charge_uah,1,1) and properties.get('Amperage')=='sint32:'+str(int(current_ua/1000))
        invalid=(current,charge,cv,qv)==(-(1<<31),-(1<<63),0,0) and properties.get('Amperage')=='<absent>' and properties.get('InstantAmperage')=='<absent>'
        records.append({'iteration':int(header[1]),'fresh':fresh,'invalid':invalid})
    fresh=[r['iteration'] for r in records if r['fresh']]
    invalid=[r['iteration'] for r in records if r['invalid']]
    assert len(fresh)>=2, 'no repeated valid native signed current/CAR plus original IOKit current'
    if require_fault:
        assert len(invalid)>=2 and max(invalid)>min(fresh), 'no repeated post-valid fault invalidation'
    assert 'panic(cpu' not in text, 'kernel panic'
    return {'passed':True,'serial_sha256':hashlib.sha256(data).hexdigest(),
            'expected_current_ua':current_ua,'expected_charge_uah':charge_uah,
            'fresh_iterations':fresh,'invalid_iterations':invalid,
            'complete_observations':len(records),'unknown_battery_properties_absent':list(absent),
            'physical_hardware_tested':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('serial',type=Path)
    p.add_argument('--current-ua',type=int,required=True)
    p.add_argument('--charge-uah',type=int,required=True)
    p.add_argument('--require-fault',action='store_true')
    a=p.parse_args()
    print(json.dumps(check(a.serial,a.current_ua,a.charge_uah,a.require_fault),indent=2))

if __name__=='__main__':main()
