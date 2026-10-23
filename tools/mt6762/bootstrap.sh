#!/usr/bin/env bash
# Install all acquired files under this directory; no system or shell-profile changes.
set -euo pipefail
XNU_TREE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
PORT=${MTK_WORKSPACE:-$(dirname "$XNU_TREE")}
mkdir -p "$PORT"
PORT=$(cd "$PORT" && pwd)
HERE="$PORT/toolchain"
REF="$PORT/references/hackios-xnu-kernel"
REF_COMMIT=d82c64a3a31cd27a0a0afbf6e213e467e44b1b4c
SDK_COMMIT=0222fd5413cf4b9af096f37b4621afa2688572f7
TOOLCHAIN_URL=https://github.com/L1ghtmann/llvm-project/releases/download/test-210562a/iOSToolchain-x86_64.tar.xz
TOOLCHAIN_SHA256=a72a7a577e2fbe2838b6b5e9c72034fa7d114af96f0e1d4b016f18730ce4056e
if [[ -z ${MTK_LLVM_BIN:-} ]]; then
  compiler=$(command -v clang || true)
  [[ -n "$compiler" ]] || { echo 'Set MTK_LLVM_BIN to a Linux LLVM bin directory (clang, clang++, dsymutil).' >&2; exit 1; }
  MTK_LLVM_BIN=$(dirname "$(readlink -f "$compiler")")
fi
export MTK_LLVM_BIN
for tool in clang clang++ dsymutil; do
  [[ -x "$MTK_LLVM_BIN/$tool" ]] || { echo "Missing $MTK_LLVM_BIN/$tool" >&2; exit 1; }
done
if [[ ! -d "$REF/.git" ]]; then
  mkdir -p "$REF"
  git -C "$REF" init -q
  git -C "$REF" remote add origin https://github.com/oosexgang/hackios-xnu-kernel.git
  git -C "$REF" fetch --depth 1 origin "$REF_COMMIT"
  git -C "$REF" checkout --detach FETCH_HEAD
fi
test "$(git -C "$REF" rev-parse HEAD)" = "$REF_COMMIT"
mkdir -p "$HERE/downloads" "$HERE/theos/toolchain" "$HERE/bin"
archive="$HERE/downloads/iOSToolchain-x86_64.tar.xz"
if [[ ! -f "$archive" ]]; then
  curl -fL --retry 3 "$TOOLCHAIN_URL" -o "$archive.part"
  mv "$archive.part" "$archive"
fi
printf '%s  %s\n' "$TOOLCHAIN_SHA256" "$archive" | sha256sum -c -
if [[ ! -x "$HERE/theos/toolchain/linux/iphone/bin/ld" ]]; then
  tar -xJf "$archive" -C "$HERE/theos/toolchain"
fi
if [[ ! -d "$HERE/theos/sdks/.git" ]]; then
  git clone --filter=blob:none --no-checkout https://github.com/theos/sdks.git "$HERE/theos/sdks"
  git -C "$HERE/theos/sdks" sparse-checkout set iPhoneOS16.5.sdk
  git -C "$HERE/theos/sdks" checkout --detach "$SDK_COMMIT"
fi
test "$(git -C "$HERE/theos/sdks" rev-parse HEAD)" = "$SDK_COMMIT"
for tool in clang clang++ ld.lld ld64.lld llvm-ar llvm-objcopy llvm-objdump llvm-nm; do
  [[ -e "$HERE/bin/$tool" ]] || ln -s "$MTK_LLVM_BIN/$tool" "$HERE/bin/$tool"
done
if [[ ! -d "$HERE/hackios-build" ]]; then
  mkdir "$HERE/hackios-build"
  cp -a "$REF/xnu-deps" "$REF/xnu-build.sh" "$REF/xnu-env.sh" "$HERE/hackios-build/"
fi
python3 - "$HERE/hackios-build/xnu-deps/host/bin/xnu-clang" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
s = s.replace('exec /usr/bin/$drv ', 'exec "${MTK_LLVM_BIN:?source toolchain/env.sh}/$drv" ')
if '-mcpu=cortex-a53' not in s:
    s = s.replace('-w "${extra[@]}" "${args[@]}"', '-w "${extra[@]}" "${args[@]}" -mcpu=cortex-a53')
p.write_text(s)
for relative in ('../../setup.sh', '../../build/pthread/build.sh'):
    helper = p.parent / relative
    text = helper.read_text()
    helper.write_text(text.replace('-DARM64_BOARD_CONFIG_BCM2837', '-DARM64_BOARD_CONFIG_${MACHINE:-BCM2837}'))
PY
# Environment is confined to this process; never export the donor's generic JOBS
# variable into an interactive shell (its userland scripts use JOBS for daemons).
export THEOS="$HERE/theos" XNU_SRC="$XNU_TREE"
export PATH="$HERE/bin:$PATH"
export MACHINE=MT6762
export JOBS=${MTK_BUILD_JOBS:-12}
[[ -e "$HERE/hackios-build/xnu-deps/host/bin/dsymutil" ]] || ln -s "$MTK_LLVM_BIN/dsymutil" "$HERE/hackios-build/xnu-deps/host/bin/dsymutil"
"$HERE/hackios-build/xnu-deps/setup.sh" --stage1
"$MTK_LLVM_BIN/clang" --version
"$THEOS/toolchain/linux/iphone/bin/ld" -v
echo 'Ready. Run tools/mt6762/build.sh with the same MTK_WORKSPACE and MTK_LLVM_BIN.'
