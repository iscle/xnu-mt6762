#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
test_bin=$(mktemp)
trap 'rm -f "$test_bin"' EXIT
${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic test_trial.c -o "$test_bin"
"$test_bin"
python3 test_worker.py
