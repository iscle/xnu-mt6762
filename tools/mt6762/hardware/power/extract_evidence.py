#!/usr/bin/env python3
"""Extract only selected technical power-probe records from expdb, with offsets."""
import argparse, hashlib, json, re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('dump',type=Path);p.add_argument('output',type=Path)
a=p.parse_args();b=a.dump.read_bytes()
patterns=[r'\[psc5425e_hw_component_detect\].{0,100}',r'\[eta6947_hw_component_detect\].{0,100}',
 r'eta6947: probe of 5-0063 failed.{0,50}',r'\[PMIC\]MT6357 CHIP Code.{0,40}',
 r'\[pmic_init\] MT6357 CHIP Code.{0,40}',r'\[psc5425e_config_interface\].{0,100}',
 r'\[psc5425e_read_interface\] Reg\[3\].{0,30}',r'input: mtk-kpd as .{0,100}',
 r'input: mtk-pmic-keys as .{0,160}',r'psc5425e_parse_dt: no (?:charger|alias) name',
 r'mt6357_charger_type_probe.{0,100}']
rx=re.compile('|'.join(patterns))
records=[]
for s in re.finditer(rb'[\x20-\x7e\t]{10,700}',b):
 for m in rx.finditer(s.group().decode('ascii')):
  records.append({'offset':hex(s.start()+m.start()),'text':m.group()})
a.output.write_text(json.dumps({'source':a.dump.name,'sha256':hashlib.sha256(b).hexdigest(),'records':records},indent=2)+'\n')
print(f'{len(records)} narrowly selected records saved')
