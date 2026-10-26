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
SOURCE_SHA=$(python3 - "$HERE/desktop_bootstrap.c" <<'PY'
import hashlib, pathlib, sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
COMPILE=("$MTK_LLVM_BIN/clang" --target=arm64-apple-ios16.5 -mcpu=cortex-a53 -Os \
  -ffreestanding -fno-stack-protector -fno-builtin -nostdlib -Wall -Wextra -Werror \
  -c "$HERE/desktop_bootstrap.c" -o "$OUT/desktop_bootstrap.o")
LINK=("$LD64" -arch arm64 -platform_version ios 16.5 16.5 -e _start \
  -pagezero_size 0x100000000 -static -o "$OUT/desktop_bootstrap.macho" "$OUT/desktop_bootstrap.o")
"${COMPILE[@]}"
"${LINK[@]}"
python3 - "$HERE/desktop_bootstrap.c" "$SOURCE_SHA" "$OUT" "${#COMPILE[@]}" "${COMPILE[@]}" "${LINK[@]}" <<'PY'
import hashlib, json, pathlib, sys
source, expected, output = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
count = int(sys.argv[4])
compile_command, link_command = sys.argv[5:5+count], sys.argv[5+count:]
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
actual = digest(source)
if actual != expected:
    raise SystemExit('Bootstrap source changed during build; reject artifact')
files = [source, source.parent/'build_desktop_bootstrap.sh',
         pathlib.Path(compile_command[0]), pathlib.Path(link_command[0]),
         output/'desktop_bootstrap.o', output/'desktop_bootstrap.macho']
report = dict(source_unchanged_during_build=True,
              compile_command=compile_command, link_command=link_command,
              files=[dict(path=str(p.resolve()), sha256=digest(p)) for p in files])
(output/'build-evidence.json').write_text(json.dumps(report, indent=2)+'\n')
PY
echo "$OUT/desktop_bootstrap.macho"
