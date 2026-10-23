#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror opp_policy.c test_opp_policy.c -o "$testdir/test-opp"
"$testdir/test-opp"
