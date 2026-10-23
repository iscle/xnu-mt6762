#!/usr/bin/env python3
"""Send synthetic AXS packets through QEMU I2C/APDMA, never a guest queue."""
import argparse
import json
import socket
import time


def frame(points):
    """points is a sequence of (contact_id, x, y), using stock sensor units."""
    if len(points) > 5 or len({p[0] for p in points}) != len(points):
        raise ValueError('At most five unique contacts are supported')
    packet = bytearray(32)
    packet[1] = len(points)
    for n, (contact, x, y) in enumerate(points):
        if not all(isinstance(v, int) for v in (contact, x, y)) or not (0 <= contact < 5 and 0 <= x <= 384 and 0 <= y <= 854):
            raise ValueError('Contact ID or sensor coordinates out of range')
        offset = 2 + 6 * n
        packet[offset:offset + 6] = bytes((0x80 | (x >> 8), x & 255,
                                         (contact << 4) | (y >> 8), y & 255, 63, 0x90))
    return packet.hex()


def send_frame(command, points, timeout=5):
    command('qom-set', path='/machine', property='lab-touch-frame', value=frame(points))
    def reads():
        return json.loads(command('qom-get', path='/machine', property='lab-i2c-state'))['i2c0']['dma_reads']
    before = reads()
    deadline = time.monotonic() + timeout
    # Observe two complete DMA reads after publication, avoiding an in-flight
    # old packet. This also scales to slower eight-core TCG runs.
    while reads() < before + 2:
        if time.monotonic() >= deadline:
            raise TimeoutError('Native guest did not consume the AXS packet')
        time.sleep(.01)


class QMP:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(5)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile('rwb', buffering=0)
        if 'QMP' not in json.loads(self.stream.readline()):
            raise RuntimeError('Missing QMP greeting')
        self.command('qmp_capabilities')

    def command(self, command, **arguments):
        self.stream.write((json.dumps({'execute': command, 'arguments': arguments}) + '\n').encode())
        while True:
            line = self.stream.readline()
            if not line:
                raise EOFError('QMP connection closed')
            answer = json.loads(line)
            if 'error' in answer:
                raise RuntimeError(answer['error'])
            if 'return' in answer:
                return answer['return']

    def close(self):
        self.stream.close()
        self.socket.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qmp', required=True, help='Socket of an explicitly enabled lab-i2c QEMU')
    p.add_argument('--from', dest='start', type=int, nargs=2, required=True, metavar=('X', 'Y'))
    p.add_argument('--to', dest='end', type=int, nargs=2, metavar=('X', 'Y'))
    p.add_argument('--steps', type=int, default=24, help='Two consumed 8ms polls per step; default about384ms')
    a = p.parse_args()
    end = a.end or a.start
    frame([(0, *a.start)]); frame([(0, *end)])
    if not 2 <= a.steps <= 120:
        p.error('--steps must be2..120')
    q = QMP(a.qmp)
    try:
        for i in range(a.steps):
            point = [round(a.start[n] + (end[n] - a.start[n]) * i / (a.steps - 1)) for n in (0, 1)]
            send_frame(q.command, [(0, *point)])
        send_frame(q.command, [])
        print(json.dumps({'synthetic_only': True, 'path': 'AXS/I2C/APDMA/native worker',
                          'start': a.start, 'end': end, 'steps_consumed': a.steps, 'release_consumed': True}))
    finally:
        # Leave a zero-contact override, even after a failed gesture. The native
        # worker independently releases contacts on transport faults/timeouts.
        try:
            q.command('qom-set', path='/machine', property='lab-touch-frame', value=frame([]))
        finally:
            q.close()


if __name__ == '__main__':
    main()
