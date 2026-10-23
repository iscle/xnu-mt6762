#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
test_bin=$(mktemp)
trap 'rm -f "$test_bin"' EXIT
${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic mtk_i2c_v2.c test_i2c.c -o "$test_bin"
"$test_bin"
