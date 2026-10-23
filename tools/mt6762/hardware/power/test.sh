#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -g power_protocol.c test_power_protocol.c -o "$testdir/test-power"
cc -std=c11 -Wall -Wextra -Werror -g thermistor.c test_thermistor.c -o "$testdir/test-thermistor"
"$testdir/test-power"
"$testdir/test-thermistor"
