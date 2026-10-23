#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror opp_policy.c test_opp_policy.c -o "$testdir/test-opp"
"$testdir/test-opp"

python3 - "$testdir/pvt_fixture.h" <<'PVT'
import json,sys
from pathlib import Path
rows=json.loads(Path('evidence/stock-c62-pvt.json').read_text())['rows']
words=[0]*144
for d in range(3):
 for i,(mhz,selector,post,clk) in enumerate(rows[d*16:(d+1)*16]):
  words[d*36+i]=mhz|(selector<<16)
  words[d*36+16+i]=post|(clk<<16)
 words[d*36+32]=0xffffffff
Path(sys.argv[1]).write_text('static const uint32_t pvt_fixture[144]={'+','.join(hex(x)+'u' for x in words)+'};\n')
PVT
cc -std=c11 -Wall -Wextra -Werror -g -I "$testdir" test_native_cpufreq.c -o "$testdir/test-native-cpufreq"
"$testdir/test-native-cpufreq"
cc -std=c11 -Wall -Wextra -Werror -g test_native_sspm.c -o "$testdir/test-native-sspm"
"$testdir/test-native-sspm"
