#!/usr/bin/env python3
"""Run an existing lab manifest and capture its synthetic framebuffer via QMP.

The PNG is a RAM snapshot, not proof of a real MediaTek display driver.
This launches no hardware connection and always terminates its own QEMU.
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--seconds', type=float, default=75)
    parser.add_argument('--label', default='capture')
    parser.add_argument('--sample-every', type=float, default=0,
                        help='Also save numbered framebuffer snapshots at this interval')
    args = parser.parse_args()
    if args.seconds < 0 or args.sample_every < 0 or '/' in args.label or not args.label:
        raise ValueError('Invalid capture duration or label')
    manifest = json.loads(args.manifest.read_text())
    fb = manifest.get('framebuffer')
    if not fb or not fb.get('simulated_ram_only'):
        raise ValueError('Manifest has no synthetic framebuffer')
    out = args.manifest.resolve().parent
    sockpath = out / (args.label + '.qmp')
    # Never unlink an existing monitor: another experiment may own it.
    if sockpath.exists():
        raise ValueError('QMP socket already exists: ' + str(sockpath))
    raw = out / (args.label + '.bgra')
    transcript = []
    qemu = None
    with (out / (args.label + '.serial.log')).open('w') as serial:
        try:
            qemu = subprocess.Popen(manifest['command'] + ['-qmp', f'unix:{sockpath},server=on,wait=off'],
                                    stdout=serial, stderr=subprocess.STDOUT)
            for _ in range(100):
                if qemu.poll() is not None:
                    raise RuntimeError('QEMU exited before QMP became available')
                if sockpath.exists():
                    break
                time.sleep(0.1)
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(10)
                client.connect(str(sockpath))
                reader = client.makefile('rb')
                transcript.append(json.loads(reader.readline()))

                def execute(command, arguments=None):
                    request = {'execute': command}
                    if arguments is not None:
                        request['arguments'] = arguments
                    client.sendall(json.dumps(request).encode() + b'\n')
                    while True:
                        result = json.loads(reader.readline())
                        transcript.append(result)
                        if 'error' in result:
                            raise RuntimeError(result['error'])
                        if 'return' in result:
                            return result['return']

                execute('qmp_capabilities')
                started = time.monotonic()
                deadline = started + args.seconds
                next_sample = started + args.sample_every if args.sample_every else deadline
                sample = 0
                while time.monotonic() < deadline:
                    if qemu.poll() is not None:
                        raise RuntimeError('QEMU exited during capture wait')
                    if args.sample_every and time.monotonic() >= next_sample:
                        sample += 1
                        sample_raw = out / f'{args.label}-{sample:03d}.bgra'
                        execute('stop')
                        execute('pmemsave', {'val': fb['addr'], 'size': fb['size'], 'filename': str(sample_raw)})
                        execute('cont')
                        save_png(sample_raw, fb)
                        next_sample += args.sample_every
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
                execute('stop')
                execute('pmemsave', {'val': fb['addr'], 'size': fb['size'], 'filename': str(raw)})
                execute('quit')
                reader.close()
        finally:
            if qemu is not None and qemu.poll() is None:
                qemu.terminate()
                try:
                    qemu.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    qemu.kill()
                    qemu.wait()
            (out / (args.label + '.qmp.json')).write_text(json.dumps(transcript, indent=2) + '\n')
    filename, visible = save_png(raw, fb)
    print(json.dumps({'png': str(filename), 'distinct_bytes': len(set(visible)),
                      'synthetic_ram_only': True}))


def save_png(raw, fb):
    from PIL import Image
    data = raw.read_bytes()
    visible = data[:fb['stride'] * fb['height']]
    image = Image.frombytes('RGBA', (fb['width'], fb['height']), visible, 'raw', 'BGRA', fb['stride'])
    filename = raw.with_suffix('.png')
    image.convert('RGB').save(filename)
    return filename, visible


if __name__ == '__main__':
    main()
