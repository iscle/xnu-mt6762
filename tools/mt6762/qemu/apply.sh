#!/usr/bin/env bash
# Create an isolated local research fork at the exact upstream source revision.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEST=${1:?Usage: apply.sh NEW_QEMU_DIRECTORY}
UPSTREAM=b6c4b7e86dec12d07f5cac65265b986d38ee9002
EXPECTED_TREE=b49e912496e9e0b42294f5998473ab9a0c0a18ea
[[ ! -e "$DEST" ]] || { echo "Destination already exists: $DEST" >&2; exit 1; }
(cd "$HERE" && sha256sum -c SHA256SUMS)
mkdir -p "$DEST"
git -C "$DEST" init -q
git -C "$DEST" remote add upstream https://github.com/qemu/qemu.git
git -C "$DEST" fetch --depth 1 upstream "$UPSTREAM"
git -C "$DEST" checkout -q -b mt6762-bringup FETCH_HEAD
[[ $(git -C "$DEST" rev-parse HEAD) == "$UPSTREAM" ]]
git -C "$DEST" -c user.name='MT6762 local build' \
    -c user.email='mt6762-build@localhost' am "$HERE"/000*.patch
[[ $(git -C "$DEST" rev-parse 'HEAD^{tree}') == "$EXPECTED_TREE" ]] || {
    echo 'Patched tree does not match the validated source tree.' >&2
    exit 1
}
echo "Prepared experimental QEMU source at $DEST"
