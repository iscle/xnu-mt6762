#!/usr/bin/env bash
# Reuse pinned acquired tools/sources; prepare only this monorepo's SDK overlay.
# No old kernel/helper checkout copy, network fetch, IIG shim or kernel build.
set -euo pipefail
XNU_TREE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
MONOREPO=$(cd "$XNU_TREE/../.." && pwd)
[[ -f "$MONOREPO/devices/mt6762/build_inputs.py" ]] || { echo 'Use the migrated HakiOS monorepo.' >&2; exit 1; }
export MTK_WORKSPACE=${MTK_WORKSPACE:-$(dirname "$MONOREPO")}
export XNU_SRC="$XNU_TREE" MACHINE=MT6762 JOBS=${MTK_BUILD_JOBS:-12}
source "$MONOREPO/xnu-env.sh"
if [[ ${1:-} == --check && $# == 1 ]]; then
  exec python3 "$MONOREPO/devices/mt6762/build_inputs.py" check-reuse
fi
[[ $# == 0 ]] || { echo 'Usage: bootstrap.sh [--check]' >&2; exit 1; }
exec "$MONOREPO/xnu-deps/setup.sh" --stage1
