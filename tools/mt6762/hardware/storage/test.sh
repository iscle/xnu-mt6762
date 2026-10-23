#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -g test_msdc_pio.c -o "$testdir/msdc-pio"
"$testdir/msdc-pio"
cc -std=c11 -Wall -Wextra -Werror -g test_msdc_clock.c -o "$testdir/msdc-clock"
"$testdir/msdc-clock"
