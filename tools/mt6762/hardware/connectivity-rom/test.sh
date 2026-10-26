#!/bin/sh
set -eu
cd "$(dirname "$0")"
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT HUP INT TERM
if [ "${SANITIZE:-0}" = 1 ]; then
    cc -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
        -fno-omit-frame-pointer conn_rom.c sha256.c test_conn_rom.c -o "$testdir/test"
else
    cc -std=c11 -Wall -Wextra -Werror -O2 conn_rom.c sha256.c test_conn_rom.c -o "$testdir/test"
fi
"$testdir/test" "$@"
if [ -n "${CLANG:-}" ]; then
    rom_clang=$CLANG
elif command -v clang >/dev/null 2>&1; then
    rom_clang=$(command -v clang)
else
    rom_clang="$(pwd)/../../../../../../../toolchain/theos/toolchain/linux/iphone/bin/clang-11"
fi
for source in conn_rom sha256; do
    "$rom_clang" --target=aarch64-none-elf -std=c11 -ffreestanding -fno-builtin \
        -Wall -Wextra -Werror -O2 -c "$source.c" -o "$testdir/$source.o"
done
python3 - "$testdir/conn_rom.o" "$testdir/sha256.o" <<'PY'
import sys
from elftools.elf.elffile import ELFFile
defined,undefined=set(),set()
for path in sys.argv[1:]:
    with open(path,'rb') as f:
        elf=ELFFile(f)
        assert elf['e_machine']=='EM_AARCH64'
        for s in elf.get_section_by_name('.symtab').iter_symbols():
            if s['st_shndx']=='SHN_UNDEF' and s.name: undefined.add(s.name)
            elif s['st_info']['bind']=='STB_GLOBAL': defined.add(s.name)
assert not undefined-defined,sorted(undefined-defined)
print('Actual core+SHA strict freestanding AArch64 compile; no external runtime dependencies PASS')
PY
