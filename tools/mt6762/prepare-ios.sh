#!/usr/bin/env bash
# Build our helper programs and package precompiled Apple iOS16.5 donor files.
# --check performs read-only byte-preservation checks, without downloading/building.
set -euo pipefail
SCRIPT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
XNU_TREE=$(cd "$SCRIPT/../.." && pwd)
WORK=${MTK_WORKSPACE:-$(dirname "$XNU_TREE")}
RUNTIME=${MTK_RUNTIME_DIR:-$WORK/runtime}
KERNEL_SHA=d82c64a3a31cd27a0a0afbf6e213e467e44b1b4c
USERLAND_SHA=a79ff0772a3454fd1ef127e181e5b3bce6c9ce18
MARKER="$RUNTIME/.mt6762-runtime.json"
MODE=${1:-build}
[[ $# -le 1 && ( "$MODE" == build || "$MODE" == --check ) ]] || {
  echo 'Usage: prepare-ios.sh [--check]' >&2; exit 2;
}
[[ ! -L "$RUNTIME" ]] || { echo 'Runtime directory must not be a symlink.' >&2; exit 1; }
if [[ -e "$RUNTIME" ]]; then
  [[ -f "$MARKER" ]] || {
    echo "Refusing existing unmarked directory: $RUNTIME. Choose a new MTK_RUNTIME_DIR." >&2; exit 1;
  }
  python3 - "$MARKER" "$KERNEL_SHA" "$USERLAND_SHA" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]); marker = json.loads(p.read_text())
assert marker['owner'] == 'mt6762-ios-runtime-v1', 'unrecognized runtime owner'
assert marker['kernel_reference_commit'] == sys.argv[2], 'kernel reference mismatch'
assert marker['userland_reference_commit'] == sys.argv[3], 'userland reference mismatch'
assert pathlib.Path(marker['runtime']).resolve() == p.parent.resolve(), 'runtime path mismatch'
PY
elif [[ "$MODE" == --check ]]; then
  echo "Missing runtime: $RUNTIME" >&2; exit 1
fi
if [[ "$MODE" == --check ]]; then
  exec python3 -B "$SCRIPT/verify-ios.py" "$RUNTIME"
fi
if [[ -z ${MTK_LLVM_BIN:-} ]]; then
  compiler=$(command -v clang || true)
  [[ -n "$compiler" ]] || { echo 'Set MTK_LLVM_BIN and run bootstrap.sh first.' >&2; exit 1; }
  MTK_LLVM_BIN=$(dirname "$(readlink -f "$compiler")")
fi
export MTK_LLVM_BIN
[[ -x "$MTK_LLVM_BIN/clang" ]] || { echo 'Missing selected clang.' >&2; exit 1; }
[[ -x "$WORK/toolchain/hackios-build/xnu-deps/host/bin/ld64" ]] || {
  echo 'Run tools/mt6762/bootstrap.sh first.' >&2; exit 1;
}
mkdir -p "$WORK/references"
WORK=$(cd "$WORK" && pwd)
fetch_reference() {
  local name=$1 commit=$2 repo="$WORK/references/$1"
  if [[ ! -d "$repo/.git" ]]; then
    [[ ! -e "$repo" ]] || { echo "Refusing non-repository $repo" >&2; return 1; }
    git init -q "$repo"
    git -C "$repo" remote add origin "https://github.com/oosexgang/$name.git"
    git -C "$repo" fetch --depth 1 origin "$commit"
    git -C "$repo" checkout --detach FETCH_HEAD
  fi
  [[ "$(git -C "$repo" rev-parse HEAD)" == "$commit" ]] || {
    echo "Reference commit mismatch: $repo" >&2; return 1;
  }
}
fetch_reference hackios-xnu-kernel "$KERNEL_SHA"
fetch_reference hackios-xnu-userland "$USERLAND_SHA"
if [[ ! -e "$RUNTIME" ]]; then
  mkdir -p "$RUNTIME"
  git -C "$WORK/references/hackios-xnu-kernel" archive "$KERNEL_SHA" | tar -x -C "$RUNTIME"
  git -C "$WORK/references/hackios-xnu-userland" archive "$USERLAND_SHA" |
    tar -x -C "$RUNTIME" --anchored --exclude=LICENSE --exclude=README.md --exclude=.gitignore
  git -C "$WORK/references/hackios-xnu-userland" show "$USERLAND_SHA:LICENSE" > "$RUNTIME/LICENSE.userland"
  cp "$RUNTIME/xnu-env.sh" "$RUNTIME/xnu-env.upstream.sh"
  python3 - "$MARKER" "$KERNEL_SHA" "$USERLAND_SHA" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
p.write_text(json.dumps({'owner':'mt6762-ios-runtime-v1', 'runtime':str(p.parent.resolve()),
  'kernel_reference_commit':sys.argv[2], 'userland_reference_commit':sys.argv[3]}, indent=2)+'\n')
PY
fi
RUNTIME=$(cd "$RUNTIME" && pwd)
exec 9> "$RUNTIME/.prepare-ios.lock"
flock -n 9 || { echo 'Another preparation process owns this runtime.' >&2; exit 1; }
# The pinned donor reused the optional-job filename as an environment-key loop
# variable. That silently overwrote every optional plist with RWA_PACKED16.
JOB_PATCH="$SCRIPT/patches/userland-mkjobs-filenames.patch"
if (cd "$RUNTIME"; git apply --check "$JOB_PATCH") 2>/dev/null; then
  (cd "$RUNTIME"; git apply "$JOB_PATCH")
elif ! (cd "$RUNTIME"; git apply --reverse --check "$JOB_PATCH"); then
  echo 'Optional-job source differs from both the pinned and patched versions.' >&2; exit 1
fi
cat > "$RUNTIME/xnu-env.sh" <<'ENV'
# Local build dependencies; only project helpers are rebuilt, never Apple's binaries.
MTK_RUNTIME_WORKSPACE=${MTK_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
export THEOS=${THEOS:-$MTK_RUNTIME_WORKSPACE/toolchain/theos}
export XNU_SRC=${XNU_SRC:-$MTK_RUNTIME_WORKSPACE/xnu}
export PATH="$MTK_RUNTIME_WORKSPACE/toolchain/bin:$PATH"
source "$MTK_RUNTIME_WORKSPACE/toolchain/hackios-build/xnu-env.sh"
unset JOBS
ENV
export MTK_WORKSPACE="$WORK" THEOS="$WORK/toolchain/theos" XNU_SRC="$XNU_TREE"
export PATH="$WORK/toolchain/bin:$PATH"
unset JOBS PREBUILT GL ADSP FLASHBOOT JB SYSTEM INJECT RC RC_JOBS EXTRA EXTRA_SHARE
LOGDIR="$RUNTIME/logs/prepare-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$LOGDIR"
echo 'Fetching Apple donor files. The donor recipe trims fonts/resources; Apple Mach-O executables remain precompiled.'
echo "Logs: $LOGDIR"
(cd "$RUNTIME"; KEEP=1 bash ios165/fetch.sh) > "$LOGDIR/fetch.log" 2>&1 || {
  tail -50 "$LOGDIR/fetch.log" >&2; exit 1;
}
python3 -B "$SCRIPT/verify-ios.py" --sources-only "$RUNTIME" > "$LOGDIR/apple-before.json"
(cd "$RUNTIME"; REST=1 WIFID=0 bash userland/build.sh) > "$LOGDIR/build.log" 2>&1 || {
  tail -60 "$LOGDIR/build.log" >&2; exit 1;
}
python3 -B "$SCRIPT/verify-ios.py" "$RUNTIME" --baseline "$LOGDIR/apple-before.json" > "$LOGDIR/verification.json"
echo "Images ready: $RUNTIME/userland/root.apfs and $RUNTIME/userland/system.apfs"
echo "Apple byte-preservation report: $LOGDIR/verification.json"
