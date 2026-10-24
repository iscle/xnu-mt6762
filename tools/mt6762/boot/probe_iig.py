#!/usr/bin/env python3
"""Run a bounded synthetic kernel RPC selftest through a static PID1 observer."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--expected-cases', type=int, required=True)
    p.add_argument('--expect-disabled', action='store_true')
    p.add_argument('--seconds', type=int, default=30)
    p.add_argument('--label', default='iig')
    a = p.parse_args()
    if not 1 <= a.seconds <= 60 or a.expected_cases < 1 or not re.fullmatch('[A-Za-z0-9_-]+', a.label):
        p.error('choose 1..60 seconds, positive case count, simple evidence label')
    m = json.loads(a.manifest.read_text())
    if sha(Path(m['kernel'])) != m['kernel_sha256']:
        p.error('kernel changed since preparation')
    out = a.manifest.resolve().parent
    serial_path, result_path = (out / (a.label + suffix) for suffix in ('.serial.log', '.json'))
    if serial_path.exists() or result_path.exists():
        p.error('evidence label already exists')
    proc = None
    with serial_path.open('x') as serial:
        try:
            proc = subprocess.Popen(m['command'], stdout=serial, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + a.seconds
            while time.monotonic() < deadline:
                log = serial_path.read_text(errors='replace')
                if 'MT6762_IIG_PROBE_DONE' in log or 'panic(' in log or proc.poll() is not None:
                    break
                time.sleep(.1)
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
    log = serial_path.read_text(errors='replace')
    rows = re.findall(r'MT6762_IIG_SYSCTL pass=(\d+) (mt6762_iig_test_\w+)=(-?\d+) error=(-?\d+) size=(\d+)', log)
    values = {(int(run), key): (int(value), int(error), int(size)) for run, key, value, error, size in rows}
    errors = []
    if 'MT6762_IIG_PROBE_DONE' not in log or 'panic(' in log:
        errors.append('guest did not complete without panic')
    if len(rows) != 4 or len(values) != 4:
        errors.append('expected exactly two result/case observations')
    for run in (1, 2):
        for field, value in [('result', 1), ('cases', a.expected_cases)]:
            observed = values.get((run, 'mt6762_iig_test_' + field))
            wanted = (0, -45, 4) if a.expect_disabled else (value, 0, 4)
            if observed != wanted:
                errors.append(f'pass{run} {field}: expected{wanted}, observed{observed}')
    result = dict(format=1, passed=not errors, errors=errors, synthetic_only=True,
        physical_hardware_tested=False, apple_userspace_tested=False,
        expected_cases=a.expected_cases, expected_disabled=a.expect_disabled,
        observations=rows, kernel_sha256=m['kernel_sha256'],
        manifest_sha256=sha(a.manifest), qemu_sha256=sha(Path(m['command'][0])),
        serial_sha256=sha(serial_path), cpu_count=m['cpu_count'])
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
