#!/usr/bin/env bash
# Reproduce the synthetic framebuffer experiment, never a physical-phone boot.
# Only the project's launch-job metadata and scripted input are changed.
set -euo pipefail
SCRIPT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
XNU_TREE=$(cd "$SCRIPT/../.." && pwd)
WORK=${MTK_WORKSPACE:-$(dirname "$XNU_TREE")}
WORK=$(cd "$WORK" && pwd)
RUNTIME=${MTK_RUNTIME_DIR:-$WORK/runtime}
OUT=${MTK_RUN_DIR:-$WORK/boot/ios-gui-$(date -u +%Y%m%dT%H%M%SZ)-$$}
KERNEL=${MTK_KERNEL:-$XNU_TREE/BUILD/obj/DEVELOPMENT_ARM64_MT6762/mach.development.mt6762}
QEMU=${MTK_QEMU:-$WORK/qemu/build/qemu-system-aarch64}
LINUX_DTB=${MTK_LINUX_DTB:-$WORK/firmware/boot.bin.dtb}
SECONDS_TO_RUN=${MTK_RUN_SECONDS:-430}
SAMPLE_SECONDS=${MTK_SAMPLE_SECONDS:-15}
MODE=${1:-run}
CPUS=${MTK_CPUS:-1}
NATIVE=0
PREPARE_ONLY=0
[[ $# -le 1 ]] || { echo 'Expected at most one mode argument.' >&2; exit 2; }
case "$MODE" in
  run) ;;
  --prepare-only) PREPARE_ONLY=1 ;;
  --native-lab) NATIVE=1 ;;
  --native-lab-prepare-only) NATIVE=1; PREPARE_ONLY=1 ;;
  *) echo 'Usage: run-ios.sh [--prepare-only|--native-lab|--native-lab-prepare-only]' >&2; exit 2 ;;
esac
python3 - "$RUNTIME/.mt6762-runtime.json" "$SECONDS_TO_RUN" "$SAMPLE_SECONDS" "$CPUS" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); m=json.loads(p.read_text())
assert m['owner']=='mt6762-ios-runtime-v1', 'Run prepare-ios.sh first'
assert pathlib.Path(m['runtime']).resolve()==p.parent.resolve(), 'runtime ownership path mismatch'
assert 60 <= float(sys.argv[2]) <= 900, 'MTK_RUN_SECONDS must be 60..900'
assert 1 <= float(sys.argv[3]) <= 60, 'MTK_SAMPLE_SECONDS must be 1..60'
assert 1 <= int(sys.argv[4]) <= 8, 'MTK_CPUS must be 1..8'
PY
[[ ! -e "$OUT" && ! -L "$OUT" ]] || { echo "Choose a new MTK_RUN_DIR; refusing existing $OUT" >&2; exit 1; }
if [[ -z ${MTK_LLVM_BIN:-} ]]; then
  compiler=$(command -v clang || true)
  [[ -n "$compiler" ]] || { echo 'Set MTK_LLVM_BIN to the LLVM bin directory used to build XNU.' >&2; exit 1; }
  MTK_LLVM_BIN=$(dirname "$(readlink -f "$compiler")")
fi
for file in "$KERNEL" "$LINUX_DTB" "$RUNTIME/userland/system.apfs" "$RUNTIME/userland/root/sbin/init" "$RUNTIME/xnuloader/identity.h"; do
  [[ -f "$file" ]] || { echo "Missing input: $file" >&2; exit 1; }
done
for file in "$QEMU" "$MTK_LLVM_BIN/clang" "$MTK_LLVM_BIN/llvm-objcopy"; do
  [[ -x "$file" ]] || { echo "Missing executable: $file" >&2; exit 1; }
done
mkdir -p "$OUT/userland"
OUT=$(cd "$OUT" && pwd)
printf '%s\n' 'mt6762-ios-qemu-experiment-v1' > "$OUT/.mt6762-experiment"
# Copy, not a shared symlink/hardlink: this experiment owns all changed metadata.
cp -a "$RUNTIME/userland/root" "$OUT/root"
cp "$KERNEL" "$OUT/kernel.macho"
KERNEL="$OUT/kernel.macho"
cp "$RUNTIME/userland/mkjobs.py" "$OUT/userland/mkjobs.py"
JOB_PATCH="$SCRIPT/patches/userland-mkjobs-filenames.patch"
if (cd "$OUT"; git apply --check "$JOB_PATCH") 2>/dev/null; then
  (cd "$OUT"; git apply "$JOB_PATCH")
elif ! (cd "$OUT"; git apply --reverse --check "$JOB_PATCH"); then
  echo 'Unexpected mkjobs.py source; refusing to guess a patch.' >&2; exit 1
fi
rm -f "$OUT/root/LaunchDaemons/RWA_PACKED16"
IOS_JOBS=(
  com.apple.notifyd com.apple.cfprefsd.xpc.daemon com.apple.cfprefsd.xpc.daemon.system com.apple.logd
  com.apple.syslogd com.apple.distnoted.xpc.daemon com.apple.diagnosticd com.apple.fseventsd
  com.apple.containermanagerd com.apple.containermanagerd.system com.apple.runningboardd
  com.apple.backboardd com.apple.mobile.usermanagerd com.apple.mobilegestalt.xpc com.apple.lsd
  com.apple.powerd com.apple.analyticsd com.apple.logd_helper com.apple.iconservices.iconservicesagent
  com.apple.pluginkit.pkd com.apple.SpringBoard
)
env -u RWA_PACKED16 OSLOG='com.apple.SpringBoard com.apple.backboardd' \
  python3 -B "$OUT/userland/mkjobs.py" --rest "$RUNTIME/ios165/rootfs" \
  "$OUT/root/LaunchDaemons" "${IOS_JOBS[@]}" > "$OUT/jobs.log"
NATIVE_FLAGS=()
CAPTURE_FLAGS=()
if [[ "$NATIVE" == 1 ]]; then
  printf '%s\n' '# Input comes only from explicit QEMU peripheral fixtures.' > "$OUT/root/etc/rc.jobs"
  if [[ -n ${MTK_BACKLIGHT_PROBE:-} ]]; then
    [[ -f "$MTK_BACKLIGHT_PROBE" ]] || { echo 'Missing MTK_BACKLIGHT_PROBE' >&2; exit 1; }
    cp "$MTK_BACKLIGHT_PROBE" "$OUT/root/bin/backlight_probe"
    chmod 755 "$OUT/root/bin/backlight_probe"
    printf '%s\n' '/redwood/bin/backlight_probe 12' >> "$OUT/root/etc/rc.jobs"
  fi
  NATIVE_FLAGS=(--native-lab-i2c --native-lab-power --native-lab-display)
  python3 - "$SCRIPT/boot/native-input.json" "$OUT/native-input.json" "$SECONDS_TO_RUN" <<'PY_SCHEDULE'
import json,pathlib,sys
schedule=json.loads(pathlib.Path(sys.argv[1]).read_text())
schedule=[a for a in schedule if a['at'] < float(sys.argv[3])]
pathlib.Path(sys.argv[2]).write_text(json.dumps(schedule,indent=2)+'\n')
PY_SCHEDULE
  CAPTURE_FLAGS=(--native-input-schedule "$OUT/native-input.json" --stop-on-panic)
else
cat > "$OUT/root/etc/rc.jobs" <<'RC'
# Synthetic input through the project's helper, not a MediaTek touch/button driver.
/redwood/bin/rwtouch wait 260 button lock 80 wait 5 notify com.redwood.layers wait 12 tap 0.5 0.5 wait 12 swipe 0.5 0.985 0.5 0.3 350 wait 12 notify com.redwood.layers wait 12 tap 0.5 0.5 wait 12 tap 0.5 0.5 wait 12 notify com.redwood.layers
RC
fi
python3 -B "$RUNTIME/tools/apfs/mkapfs.py" -z -o "$OUT/root.apfs" "Root=$OUT/root" > "$OUT/root-image.log"
python3 -B "$SCRIPT/verify-ios.py" "$RUNTIME" --root-image "$OUT/root.apfs" > "$OUT/apple-preservation.json"
python3 -B "$SCRIPT/boot/prepare.py" --kernel "$KERNEL" --out "$OUT/payload" \
  --clang "$MTK_LLVM_BIN/clang" --objcopy "$MTK_LLVM_BIN/llvm-objcopy" \
  --qemu "$QEMU" --linux-dtb "$LINUX_DTB" --ramdisk "$RUNTIME/userland/system.apfs" \
  --ramdisk "$OUT/root.apfs" --memory-mib 4096 --framebuffer --cpus "$CPUS" "${NATIVE_FLAGS[@]}" \
  --identity-header "$RUNTIME/xnuloader/identity.h" \
  --cmdline 'debug=0x14e serial=3 keepsyms=1 -v -enable_kprintf_spam rd=md0' > "$OUT/prepare.log"
echo "Manifest: $OUT/payload/manifest.json"
if [[ "$NATIVE" == 1 ]]; then
  echo 'Explicit synthetic peripheral fixtures; native gesture results require inspecting captures and model counters.'
else
  echo 'Synthetic RAM display/input only. Apple home screen first observed around 330 seconds; widget placeholders and missing hardware services remain.'
fi
if [[ "$PREPARE_ONLY" == 0 ]]; then
  python3 -B "$SCRIPT/boot/capture.py" "$OUT/payload/manifest.json" \
    --seconds "$SECONDS_TO_RUN" --sample-every "$SAMPLE_SECONDS" --label gui "${CAPTURE_FLAGS[@]}"
  echo "Captures and serial log: $OUT/payload/gui*"
fi
