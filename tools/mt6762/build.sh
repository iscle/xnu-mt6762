#!/usr/bin/env bash
# Build a fresh linked artifact. Report donor post-link export-check failures separately.
set -euo pipefail
XNU_TREE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
MONOREPO=$(cd "$XNU_TREE/../.." && pwd)
[[ -f "$MONOREPO/devices/mt6762/build_inputs.py" ]] || { echo 'Use the migrated HakiOS monorepo.' >&2; exit 1; }
WORK=${MTK_WORKSPACE:-$(dirname "$MONOREPO")}
WORK=$(cd "$WORK" && pwd)
HELPER="$MONOREPO"
export MTK_WORKSPACE="$WORK" XNU_SRC="$XNU_TREE" MACHINE=MT6762 JOBS=${MTK_BUILD_JOBS:-12}
source "$MONOREPO/xnu-env.sh"
profile="$MONOREPO/devices/mt6762/build_inputs.py"
if [[ ${1:-} == --check && $# == 1 ]]; then
  python3 "$profile" check-reuse
  python3 "$profile" check-iig
  exit 0
fi
[[ $# == 0 ]] || { echo 'Usage: build.sh [--check]' >&2; exit 1; }
python3 "$profile" check-reuse
[[ -x "$HELPER/xnu-deps/host/bin/migcom" && -x "$HELPER/xnu-deps/host/bin/xnu-clang++" &&
   -f "$XNU_SDK_PATH/.mt6762-base-sdk" ]] || { echo 'Run the new-tree tools/mt6762/bootstrap.sh first.' >&2; exit 1; }
LOGDIR="$WORK/evidence/builds/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$LOGDIR"
# Reject stale source, wrong-tree replay and placeholder IIG before touching BUILD.
python3 "$profile" check-iig > "$LOGDIR/iig-verify.log" 2>&1 || {
  cat "$LOGDIR/iig-verify.log" >&2; exit 1;
}
python3 "$profile" snapshot "$LOGDIR/build-inputs-before.json"
python3 "$XNU_TREE/tools/mt6762/source_snapshot.py" "$XNU_TREE" "$LOGDIR/source-before.json"
python3 "$XNU_TREE/tools/mt6762/iig_snapshot.py" "$HELPER/xnu-deps/host/bin/iig" "$LOGDIR/iig-before.json"
python3 - "$XNU_TREE/BUILD" "$LOGDIR/iig-before.json" "$LOGDIR/build-inputs-before.json" <<'PYPROFILE'
import json, pathlib, sys
build = pathlib.Path(sys.argv[1])
inputs = [(build/'.mt6762-iig-inputs.json', pathlib.Path(sys.argv[2])),
          (build/'.mt6762-build-inputs.json', pathlib.Path(sys.argv[3]))]
# Never silently adopt an old BUILD or switch toolchain/IIG inside it.
if build.exists():
    for marker, source in inputs:
        if not marker.is_file() or json.loads(marker.read_text()) != json.loads(source.read_text()):
            if any(build.iterdir()):
                raise SystemExit('BUILD profile/IIG inputs changed or unmarked: preserve BUILD and create a fresh BUILD.')
build.mkdir(exist_ok=True)
for marker, source in inputs:
    marker.write_text(source.read_text())
PYPROFILE
"$HELPER/xnu-deps/setup.sh" --rebuild-libs > "$LOGDIR/dependencies.log" 2>&1 || {
  cat "$LOGDIR/dependencies.log" >&2; exit 1;
}
ARTIFACT="$XNU_TREE/BUILD/obj/DEVELOPMENT_ARM64_MT6762/mach.development.mt6762"
# Preserve previous outputs, but require this invocation to link and strip anew.
for file in "$ARTIFACT" "$ARTIFACT.unstripped"; do
  [[ ! -f "$file" ]] || mv "$file" "$LOGDIR/$(basename "$file").previous"
done
set +e
"$HELPER/xnu-build.sh" -j"$JOBS" -k > "$LOGDIR/make.log" 2>&1
result=$?
set -e
python3 "$XNU_TREE/tools/mt6762/source_snapshot.py" "$XNU_TREE" "$LOGDIR/source-after.json"
python3 "$profile" snapshot "$LOGDIR/build-inputs-after.json"
python3 "$XNU_TREE/tools/mt6762/iig_snapshot.py" "$HELPER/xnu-deps/host/bin/iig" "$LOGDIR/iig-after.json"
python3 - "$ARTIFACT" "$LOGDIR" "$result" "$XNU_TREE" <<'PY'
import hashlib, json, pathlib, re, struct, subprocess, sys
artifact, logs, rc, source = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
log = (logs/'make.log').read_text(errors='replace')
errors = [line for line in log.splitlines() if re.search(r'make(?:\[\d+\])?: \*\*\* .*Error \d+', line)]
allowed = (
    r'/config/Makefile:121: check_all_exports\] Error 1',
    r'/config/Makefile:108: .*/config/(?:IOKit|Libkern|Private)\.symbolset\] Error 1',
    r'/makedefs/MakeInc\.dir:\d+: config_all(?:_recurse_into_config)?\] Error 2',
    r'/makedefs/MakeInc\.top:\d+: config_all_bootstrap_DEVELOPMENT\^ARM64\^MT6762\] Error 2',
    r'\[Makefile:239: all\] Error 2',
)
known_postlink = (rc == 2 and errors and 'exported name not in import list:' in log
                 and all(any(re.search(p, line) for p in allowed) for line in errors)
                 and not re.search(r'(?:fatal error:|clang(?:\+\+)?: error:|Undefined symbols|command not found|No rule to make target|missing separator|recipe commences before first target|unterminated variable reference|No such file or directory|Segmentation fault)', log)
                 and not any('***' in line and not re.search(r'Error \d+', line)
                             for line in log.splitlines() if re.match(r'make(?:\[\d+\])?:', line)))
linked = artifact.is_file() and artifact.stat().st_size > 4096 and 'LD mach.development.mt6762.unstripped' in log
valid_header = False
if linked:
    header = artifact.read_bytes()[:32]
    magic, cpu, subtype, filetype = struct.unpack_from('<IIII', header)
    valid_header = magic == 0xfeedfacf and cpu == 0x100000c and subtype == 0 and filetype == 2
before = json.loads((logs/'source-before.json').read_text())
after = json.loads((logs/'source-after.json').read_text())
changed = sorted(name for name in before['files'].keys() | after['files'].keys()
                 if before['files'].get(name) != after['files'].get(name))
iig_before = json.loads((logs/'iig-before.json').read_text())
iig_after = json.loads((logs/'iig-after.json').read_text())
iig_stable = iig_before == iig_after
build_before = json.loads((logs/'build-inputs-before.json').read_text())
build_after = json.loads((logs/'build-inputs-after.json').read_text())
build_stable = build_before == build_after
build_changed = sorted(name for name in build_before['files'].keys() | build_after['files'].keys()
                       if build_before['files'].get(name) != build_after['files'].get(name))
accepted = bool(linked and valid_header and not changed and iig_stable and build_stable and (rc == 0 or known_postlink))
report = {
    'artifact_ready': accepted, 'artifact': str(artifact), 'make_exit_code': rc,
    'all_checks_passed': accepted and rc == 0, 'make_checks_passed': rc == 0, 'known_postlink_export_failures_only': bool(known_postlink),
    'new_link_observed': linked, 'macho_arm64_executable': valid_header,
    'kernel_source_sha256': after['sha256'], 'source_unchanged_during_build': not changed,
    'source_files_changed_during_build': changed,
    'build_inputs_unchanged_during_build': build_stable,
    'build_input_files_changed_during_build': build_changed,
    'build_inputs_sha256': build_after['sha256'],
    'build_monorepo': build_after['monorepo'],
    'iig_inputs_unchanged_during_build': iig_stable,
    'iig_inputs_sha256': iig_after['sha256'],
    'iig_executable': iig_after['executable'],
    'iig_selected_environment': iig_after['selected_environment'],
    'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest() if linked else None,
    'source_head': subprocess.check_output(['git','-C',source,'rev-parse','HEAD'],text=True).strip(),
    'source_status': subprocess.check_output(['git','-C',source,'status','--porcelain'],text=True),
    'errors': errors, 'build_log': str(logs/'make.log'),
}
(logs/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('source_status','errors')},indent=2))
if accepted and known_postlink:
    print('Kernel linked; donor export/symbolset checks still failed. This is not a fully passing build.',file=sys.stderr)
if not accepted:
    print(f'Build rejected; inspect {logs / "make.log"}',file=sys.stderr)
sys.exit(0 if accepted else 1)
PY
