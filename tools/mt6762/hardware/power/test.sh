#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -g power_protocol.c test_power_protocol.c -o "$testdir/test-power"
cc -std=c11 -Wall -Wextra -Werror -g thermistor.c test_thermistor.c -o "$testdir/test-thermistor"
"$testdir/test-power"
"$testdir/test-thermistor"
cc -std=c11 -Wall -Wextra -Werror -g test_native_power.c -o "$testdir/test-native-power"
"$testdir/test-native-power"
cc -std=c11 -Wall -Wextra -Werror -g test_native_charger.c -o "$testdir/test-native-charger"
"$testdir/test-native-charger"
python3 test_charger_entry.py
python3 test_charger_setup.py
cc -std=c11 -Wall -Wextra -Werror -g test_charger_postsetup.c -o "$testdir/test-charger-postsetup"
"$testdir/test-charger-postsetup"
cc -std=c11 -Wall -Wextra -Werror -g test_pmic_entry.c -o "$testdir/test-pmic-entry"
"$testdir/test-pmic-entry"
python3 test_pmic_entry_integration.py
python3 test_wacs_delay.py
python3 test_gauge_baseline.py
python3 - "$testdir/gauge_vectors.h" <<'GAUGE'
import json,sys
from pathlib import Path
rows=json.loads(Path('evidence/stock-gauge-vectors.json').read_text())['cases']
text='static const long long gauge_vectors[][7]={\n'
for row in rows:
 text+='{'+','.join(str(row[k]) for k in ['current','low','high','rfg','tune','ua','uah'])+'},\n'
Path(sys.argv[1]).write_text(text+'};\n')
GAUGE
cc -std=c11 -Wall -Wextra -Werror -g -I "$testdir" test_native_gauge.c -o "$testdir/test-native-gauge"
"$testdir/test-native-gauge"
cc -std=c11 -Wall -Wextra -Werror -g test_gauge_observer.c -o "$testdir/test-gauge-observer"
"$testdir/test-gauge-observer"
python3 - "$testdir/ntc_vectors.h" <<'NTC'
import json,sys
from pathlib import Path
rows=json.loads(Path('evidence/stock-ntc-vectors.json').read_text())['cases']
text='static const int ntc_vectors[][7]={\n'
for row in rows:
 text+='{'+','.join(str(row[k]) for k in ['ntc_mv','vbif_mv','current_0p1ma','com_fg','com_rfg','no_comp','deci_c'])+'},\n'
Path(sys.argv[1]).write_text(text+'};\n')
NTC
cc -std=c11 -Wall -Wextra -Werror -g -I "$testdir" thermistor.c test_ntc_compensation.c -o "$testdir/test-ntc-compensation"
"$testdir/test-ntc-compensation"
sh ./test_bif.sh
cc -std=c11 -Wall -Wextra -Werror -g test_report_expiry.c -o "$testdir/test-report-expiry"
"$testdir/test-report-expiry"
