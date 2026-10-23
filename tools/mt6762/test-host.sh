#!/usr/bin/env bash
# Protocol/loader checks only; this does not certify native hardware support.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -B -m unittest discover -s boot -p 'test_*.py' -v
bash hardware/i2c/test.sh
bash hardware/power/test.sh
bash hardware/cpu-power/test.sh
test_bin=$(mktemp)
trap 'rm -f "$test_bin"' EXIT
for source in hardware/display-touch/test_*.c; do
  ${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic "$source" -o "$test_bin"
  "$test_bin"
done
