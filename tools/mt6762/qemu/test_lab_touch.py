#!/usr/bin/env python3
"""Validate runtime raw AXS packets through the synthetic APDMA model."""
import argparse
import importlib.util
from pathlib import Path
import tempfile
from test_lab_display import Lab

spec = importlib.util.spec_from_file_location('touch_lab', Path(__file__).resolve().parents[1] / 'boot/touch_lab.py')
touch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(touch)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu', type=Path, required=True)
    p.add_argument('--dtb', type=Path, required=True)
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='mtk-touch-') as directory:
        lab = Lab(a.qemu.resolve(), a.dtb.resolve(), directory, enabled=False, accel='qtest')
        try:
            def get():
                return lab.command('qom-get', path='/machine', property='lab-touch-frame')
            def put(value):
                lab.command('qom-set', path='/machine', property='lab-touch-frame', value=value)
            assert get() == ''
            packet = touch.frame([(0, 384, 854), (1, 0, 0), (2, 120, 200), (3, 300, 800), (4, 1, 853)])
            put(packet)
            assert get() == packet
            for bad in ('0', '00' * 31, '00' * 33, 'gg' * 32):
                try:
                    put(bad)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Malformed packet accepted')
                assert get() == packet, 'Invalid setter changed previous state'
            lab.write(0x10001084, 1 << 11)
            lab.write(0x1000108c, 1 << 18)
            def receive():
                base, dma, target = 0x11007000, 0x11000080, 0x41000000
                for offset, value in ((4, 0x77), (12, 0xffff), (16, 4), (20, 32), (24, 1)):
                    lab.access(f'writew {base + offset:#x} {value:#x}')
                for offset, value in ((24, 1), (32, target), (36, 0), (40, 32), (84, 0), (88, 0), (8, 1)):
                    lab.write(dma + offset, value)
                lab.access(f'writew {base + 36:#x} 1')
                lab.access('clock_step 1000000')
                assert int(lab.access(f'readw {base + 12:#x}'), 0) == 1
                assert lab.read(dma + 8) == 0
                return lab.access(f'read {target:#x} 32').removeprefix('0x').lower()
            assert receive() == packet
            put(touch.frame([])); assert receive() == '00' * 32
            put(''); assert get() == '' and receive() == '00' * 32
            for points in ([(0, -1, 0)], [(5, 1, 1)], [(0, 385, 0)], [(0, 0, 855)], [(0, 1, 1)] * 2):
                try:
                    touch.frame(points)
                except ValueError:
                    pass
                else:
                    raise AssertionError('Invalid contacts accepted')
            print('Synthetic raw AXS: five contacts, DMA bytes, invalid setter preservation and release passed')
        finally:
            lab.close()


if __name__ == '__main__':
    main()
