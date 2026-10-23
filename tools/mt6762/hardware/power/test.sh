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
