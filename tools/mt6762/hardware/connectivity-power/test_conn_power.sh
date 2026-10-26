#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -O2 conn_power.c test_conn_power.c -o "$testdir/test"
"$testdir/test"
if [ -n "${CLANG:-}" ]; then
    connectivity_clang=$CLANG
elif command -v clang >/dev/null 2>&1; then
    connectivity_clang=$(command -v clang)
else
    connectivity_clang="$(pwd)/../../../../../../../toolchain/theos/toolchain/linux/iphone/bin/clang-11"
fi
"$connectivity_clang" --target=aarch64-none-elf -std=c11 -ffreestanding -fno-builtin \
    -Wall -Wextra -Werror -O2 -c conn_power.c -o "$testdir/core.o"
python3 - "$testdir/core.o" <<'PY'
import sys
from elftools.elf.elffile import ELFFile
with open(sys.argv[1], 'rb') as f:
    elf = ELFFile(f)
    assert elf['e_machine'] == 'EM_AARCH64'
    undefined = [s.name for s in elf.get_section_by_name('.symtab').iter_symbols()
                 if s['st_shndx'] == 'SHN_UNDEF' and s.name]
    assert not undefined, undefined
print('CONN core freestanding AArch64 strict compile, no undefined runtime dependencies PASS')
PY
