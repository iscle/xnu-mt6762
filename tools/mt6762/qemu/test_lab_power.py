#!/usr/bin/env python3
"""Test only opt-in synthetic PWRAP/ADC/keypad MMIO; no phone access.

The qtest accelerator executes no guest instructions. Virtual-time stepping tests WACS2 busy/read-valid/clear,
conversion-ready delays, faults, command restrictions and active-low keys.
Native-worker integration is a separate full-kernel acceptance run.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from test_lab_display import Lab


class PowerLab(Lab):
    def __init__(self, qemu, dtb, directory, enabled=True):
        directory = Path(directory)
        self.log = (directory / 'qemu.log').open('w+')
        self.qmp_path = directory / 'qmp.sock'
        self.test_path = directory / 'qtest.sock'
        self.process = subprocess.Popen([
            str(qemu), '-M', 'mt6762' + (',lab-power=on' if enabled else ''),
            '-accel', 'qtest', '-cpu', 'cortex-a53', '-m', '512M', '-smp', '1',
            '-dtb', str(dtb), '-display', 'none', '-serial', 'null',
            '-monitor', 'none', '-qmp', f'unix:{self.qmp_path},server=on,wait=off',
            '-qtest', f'unix:{self.test_path},server=on,wait=off',
        ], stdout=self.log, stderr=self.log)
        self.sockets = []
        try:
            self.qmp = self.connect(self.qmp_path)
            self.test = self.connect(self.test_path)
            assert 'QMP' in json.loads(self.qmp.readline())
            self.command('qmp_capabilities')
        except BaseException:
            self.close()
            raise

    def state(self):
        return json.loads(self.command('qom-get', path='/machine', property='lab-power-state'))

    def fault(self, name):
        self.command('qom-set', path='/machine', property='lab-power-fault', value=name)

    def keys(self, mask):
        self.command('qom-set', path='/machine', property='lab-key-mask', value=mask)

    def step(self, ns):
        self.access(f'clock_step {ns}')

    def status(self):
        return self.read(0x1000dc24)

    def pmic(self, address, value=None):
        assert address % 2 == 0
        assert (self.status() >> 16) & 7 == 0
        command = (address >> 1) << 16
        if value is not None:
            command |= 0x80000000 | value
        self.write(0x1000dc20, command)
        assert (self.status() >> 16) & 7 == 2
        self.step(10000)
        if value is not None:
            assert (self.status() >> 16) & 7 == 0
            return
        assert (self.status() >> 16) & 7 == 6
        result = self.status() & 0xffff
        self.write(0x1000dc28, 1)
        assert (self.status() >> 16) & 7 == 0
        return result

    def keymem(self):
        return int(self.access('readw 0x10010004'), 0)


def exercise(lab):
    assert lab.status() == 1 << 21
    assert lab.pmic(8) == 0x5730
    assert lab.pmic(0x24) == 6 and lab.pmic(0xe08) == 1
    assert lab.keymem() == 0xffff
    for mask in range(8):
        lab.keys(mask)
        assert bool(lab.pmic(0x24) & 2) == (not bool(mask & 1))
        mem = lab.keymem()
        assert bool(mem & 2) == (not bool(mask & 2))
        assert bool(mem & 1) == (not bool(mask & 4))
    lab.keys(0)
    # Ready must remain clear before the conversion delay.
    lab.pmic(0x110e, 2)
    assert lab.pmic(0x108a) == 0
    lab.step(1280000)
    raw = lab.pmic(0x108a)
    assert raw == 0x8000 | 26700
    assert ((raw & 0x7fff) * 3 * 1800) >> 15 == 4400
    lab.pmic(0x110e, 8)
    assert lab.pmic(0x108e) == 0
    lab.step(80000)
    raw = lab.pmic(0x108e)
    assert raw == 0x8000 | 1400
    assert ((raw & 0xfff) * 1800) >> 12 == 615
    # No fabricated PMIC programming beyond the two conversion requests.
    before = lab.state()['rejected']
    lab.pmic(0x110e, 4)
    lab.pmic(0x24, 0)
    assert lab.state()['rejected'] == before + 2
    assert lab.pmic(0x24) == 6
    lab.fault('bad-id')
    assert lab.pmic(8) == 0x1234
    lab.fault('adc-timeout')
    lab.pmic(0x110e, 2)
    lab.step(40000000)
    assert lab.pmic(0x108a) == 0
    lab.fault('adc-rail')
    lab.pmic(0x110e, 8)
    lab.step(80000)
    assert lab.pmic(0x108e) == 0x8000
    lab.fault('keypad-disabled')
    assert int(lab.access('readw 0x10010024'), 0) == 0
    lab.fault('init-loss')
    assert not lab.status() & (1 << 21)
    lab.fault('none')
    assert lab.status() == 1 << 21
    # No automatic recovery from a timed-out in-flight command.
    lab.fault('stall')
    lab.write(0x1000dc20, (8 >> 1) << 16)
    lab.step(20000000)
    assert (lab.status() >> 16) & 7 == 2
    lab.fault('none')
    lab.step(20000000)
    assert (lab.status() >> 16) & 7 == 2
    before = lab.state()['rejected']
    lab.write(0x1000dc20, (8 >> 1) << 16)
    lab.write(0x1000dc28, 1)
    assert lab.state()['rejected'] == before + 2
    return lab.state()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--dtb', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mt6762-power-qtest-') as temporary:
        lab = PowerLab(args.qemu.resolve(), args.dtb.resolve(), temporary)
        try:
            result = exercise(lab)
        finally:
            lab.close()
        lab = PowerLab(args.qemu.resolve(), args.dtb.resolve(), temporary, enabled=False)
        try:
            assert lab.state() == {'enabled': False}
            assert lab.status() == 0
            assert lab.keymem() == 0
        finally:
            lab.close()
    print(json.dumps({'passed': True, 'synthetic_only': True, 'final_state': result}, indent=2))


if __name__ == '__main__':
    main()
