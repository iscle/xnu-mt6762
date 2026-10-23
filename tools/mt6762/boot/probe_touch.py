#!/usr/bin/env python3
"""Observe five native AXS contacts at the guest queue, via modeled I2C/DMA."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from touch_lab import QMP, send_frame


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--label', default='five-contacts')
    a = p.parse_args()
    if not a.label or '/' in a.label or a.label in ('.', '..'):
        raise ValueError('Invalid output label')
    m = json.loads(a.manifest.read_text())
    if not m.get('native_lab_i2c') or m.get('native_lab_touch_events'):
        raise ValueError('Requires native I2C with the automatic touch sequence disabled')
    out = a.manifest.resolve().parent
    serial_path = out / (a.label + '.serial.log')
    points = [(0, 384, 854), (1, 0, 0), (2, 120, 200), (3, 300, 800), (4, 1, 853)]
    moved = [(0, 380, 850), (1, 1, 1), (2, 121, 201), (3, 301, 801), (4, 2, 852)]
    expected = [(kind, contact, x * 65535 // 384, y * 65535 // 854)
                for kind, group in ((1, points), (2, moved), (3, moved))
                for contact, x, y in group]
    with tempfile.TemporaryDirectory(prefix='mtk-axs-') as temporary, serial_path.open('w') as serial:
        socket_path = Path(temporary) / 'qmp'
        proc = subprocess.Popen(m['command'] + ['-qmp', f'unix:{socket_path},server=on,wait=off'],
                                stdout=serial, stderr=subprocess.STDOUT)
        q = None
        try:
            deadline = time.monotonic() + 20
            while not socket_path.exists() or 'MT6762_QUEUE_READY' not in serial_path.read_text(errors='replace'):
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Native static queue observer did not become ready')
                time.sleep(.05)
            q = QMP(socket_path)
            for group in (points, moved, []):
                send_frame(q.command, group)
            deadline = time.monotonic() + 5
            while serial_path.read_text(errors='replace').count('MT6762_QUEUE type=') < len(expected):
                if time.monotonic() > deadline:
                    raise TimeoutError('Queue consumer did not report all native events')
                time.sleep(.02)
            state = json.loads(q.command('qom-get', path='/machine', property='lab-i2c-state'))
            q.command('quit')
        finally:
            if q:
                q.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
    serial = serial_path.read_text(errors='replace')
    observed = [tuple(map(int, match)) for match in re.findall(
        r'MT6762_QUEUE type=(\d+) finger=(\d+) x=(\d+) y=(\d+)', serial)]
    online = sorted(set(map(int, re.findall(r'arm_cpu_init\(\): cpu (\d+) online', serial))))
    result = {'synthetic_only': True, 'physical_hardware_tested': False,
              'kernel_sha256': m['kernel_sha256'],
              'qemu_sha256': hashlib.sha256(Path(m['command'][0]).read_bytes()).hexdigest(),
              'cpu_count': m.get('cpu_count', 1), 'secondary_cpus_online': online,
              'expected_queue': expected, 'observed_queue': observed,
              'exact_queue_match': observed == expected, 'kernel_panic': 'panic(' in serial,
              'i2c': state}
    (out / (a.label + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('expected_queue', 'observed_queue', 'i2c')}, indent=2))
    if observed != expected or result['kernel_panic'] or online != list(range(1, m.get('cpu_count', 1))):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
