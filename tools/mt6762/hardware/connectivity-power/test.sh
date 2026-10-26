#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -g test_probe.c -o "$testdir/probe"
cc -std=c11 -Wall -Wextra -Werror -g test_pwrap.c -o "$testdir/pwrap"
"$testdir/probe" "$testdir/complete.bin" "$testdir/failed.bin" "$testdir/family.bin" "$testdir/wrapped.bin" "$testdir/disabled.bin"
"$testdir/pwrap"
python3 test_record.py "$testdir/complete.bin" "$testdir/failed.bin" "$testdir/family.bin" "$testdir/wrapped.bin" "$testdir/disabled.bin"
# Prefer caller-selected compiler; this checkout can reuse its existing toolchain.
if [ -n "${CLANG:-}" ]; then
    connectivity_clang=$CLANG
elif command -v clang >/dev/null 2>&1; then
    connectivity_clang=$(command -v clang)
else
    connectivity_clang="$(pwd)/../../../../../../../toolchain/theos/toolchain/linux/iphone/bin/clang-11"
fi
"$connectivity_clang" --target=aarch64-none-elf -std=c11 -ffreestanding -fno-builtin -O2 \
    -Wall -Wextra -Werror -c freestanding.c -o "$testdir/consumer.o"
python3 - "$testdir/consumer.o" <<'PY'
import sys
from elftools.elf.elffile import ELFFile
with open(sys.argv[1], 'rb') as f:
    elf = ELFFile(f)
    assert elf['e_machine'] == 'EM_AARCH64'
    undefined = [s.name for s in elf.get_section_by_name('.symtab').iter_symbols()
                 if s['st_shndx'] == 'SHN_UNDEF' and s.name]
    assert not undefined, undefined
print('connectivity real freestanding AArch64 consumer: strict warnings and no undefined dependencies PASS')
PY
