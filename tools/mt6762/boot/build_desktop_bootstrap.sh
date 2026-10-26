#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
XNU=$(cd "$HERE/../../.." && pwd)
WORK=${MTK_WORKSPACE:-$(dirname "$XNU")}
OUT=${1:?Usage: build_desktop_bootstrap.sh NEW_OUTPUT_DIRECTORY}
[[ ! -e "$OUT" ]] || { echo "Refusing existing $OUT" >&2; exit 1; }
: "${MTK_LLVM_BIN:?Set MTK_LLVM_BIN to the LLVM directory used for XNU}"
LD64=${MTK_LD64:-$WORK/toolchain/theos/toolchain/linux/iphone/bin/ld}
[[ -x "$LD64" ]] || { echo "Missing $LD64" >&2; exit 1; }
mkdir -p "$OUT"
"$MTK_LLVM_BIN/clang" --target=arm64-apple-ios16.5 -mcpu=cortex-a53 -Os \
  -ffreestanding -fno-stack-protector -fno-builtin -nostdlib -Wall -Wextra -Werror \
  -c "$HERE/desktop_bootstrap.c" -o "$OUT/desktop_bootstrap.o"
"$LD64" -arch arm64 -platform_version ios 16.5 16.5 -e _start \
  -pagezero_size 0x100000000 -static -o "$OUT/desktop_bootstrap.macho" "$OUT/desktop_bootstrap.o"
echo "$OUT/desktop_bootstrap.macho"
