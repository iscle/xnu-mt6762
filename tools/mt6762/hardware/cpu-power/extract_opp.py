#!/usr/bin/env python3
"""Re-extract bounded CPU OPP tables and exact bin-selection records."""
import argparse,hashlib,json,re,struct,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('image',type=Path);p.add_argument('elf',type=Path)
p.add_argument('expdb',type=Path);p.add_argument('llvm_nm');p.add_argument('output',type=Path)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
b=a.image.read_bytes();base=0xffffff8008080000
assert hashlib.sha256(b).hexdigest()=='82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
nm=subprocess.check_output([a.llvm_nm,'-n',str(a.elf)],text=True)
result={}
for address,name in re.findall(r'^([0-9a-f]+) . (opp_tbl_(?:L|LL|CCI)_e\d+_0)$',nm,re.M):
 rows=[list(struct.unpack_from('<II',b,int(address,16)-base+i*8)) for i in range(16)]
 result[name]={'va':'0x'+address,'frequency_khz_voltage_10uv':rows}
(a.output/'stock-opp-tables.json').write_text(json.dumps(result,indent=2)+'\n')
d=a.expdb.read_bytes()
# Fixed four833 rates established by exact selector format and immediates;
# stop there to exclude adjacent binary ring-buffer data.
rx=rb'\[Power/cpufreq\] [0-9]+,[0-9]+,[0-9]+,[0-9]+,833,833,833,833'
records=[{'offset':hex(m.start()),'text':m.group().decode()} for m in re.finditer(rx,d)]
(a.output/'boot-cpufreq-selected.json').write_text(json.dumps(records,indent=2)+'\n')
(a.output/'source-hashes.json').write_text(json.dumps({a.image.name:hashlib.sha256(b).hexdigest(),a.elf.name:hashlib.sha256(a.elf.read_bytes()).hexdigest(),a.expdb.name:hashlib.sha256(d).hexdigest()},indent=2)+'\n')
print('Extracted',len(result),'OPP arrays and',len(records),'bin-selection records')
