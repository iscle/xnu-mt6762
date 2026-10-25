#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -g test_bif_protocol.c -o "$testdir/bif"
"$testdir/bif"
cc -std=c11 -Wall -Wextra -Werror -g test_bif_observer.c -o "$testdir/bif-observer"
"$testdir/bif-observer"
