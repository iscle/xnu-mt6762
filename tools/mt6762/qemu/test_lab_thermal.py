#!/usr/bin/env python3
"""Opt-in synthetic PMIC thermal protocol tests; never physical temperatures.

No guest CPU executes. This independently checks timer/ready/fault fixtures;
real native conversion/freshness acceptance is a separate kernel run.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from test_lab_power import PowerLab


CALIBRATION = (0x137, 1588, 0, 0, 1526, 1534)
CHANNELS = ((0x110e, 16, 0x1090, 1588),
            (0x1114, 32, 0x10d8, 1526),
            (0x1114, 64, 0x10da, 1534))


def sample(lab, channel, rail=False):
    request, bit, output, raw = CHANNELS[channel]
    lab.pmic(request, bit)
    assert lab.pmic(output) == 0  # Mandatory observed READY low.
    lab.step(80000)
    assert lab.pmic(output) == (0x8000 | (0 if rail else raw))


def exercise(lab):
    state = lab.state()
    assert state['thermal_enabled'] and state['thermal_calibration_synthetic']
    for _ in range(2):
        assert tuple(lab.pmic(0x11ae + 2 * i) for i in range(6)) == CALIBRATION
    assert lab.pmic(0x1216) == 0
    for channel in range(3):
        sample(lab, channel)
        sample(lab, channel)  # A new request clears previous READY.
    assert lab.state()['thermal_requests'] == [2, 2, 2]
    assert lab.state()['thermal_completions'] == [2, 2, 2]
    # Thermal faults leave baseline battery/NTC ADC operational.
    lab.fault('thermal-timeout')
    lab.pmic(0x110e, 16)
    lab.step(40000000)
    assert lab.pmic(0x1090) == 0
    lab.pmic(0x110e, 2)
    lab.step(1280000)
    assert lab.pmic(0x108a) == 0x8000 | 26700
    lab.fault('thermal-stale')
    lab.pmic(0x1114, 32)
    assert lab.pmic(0x10d8) & 0x8000  # Guest must reject preexisting READY.
    lab.fault('thermal-uncalibrated')
    assert not lab.pmic(0x11ae) & 256
    lab.fault('thermal-bad-degc')
    assert lab.pmic(0x11ae) & 63 == 1
    lab.fault('thermal-mux')
    assert lab.pmic(0x1216) & 16  # Shared die channel belongs to DCXO.
    lab.fault('thermal-rail')
    for channel in range(3):
        sample(lab, channel, rail=True)
    lab.fault('none')
    before = lab.state()['rejected']
    lab.pmic(0x1216, 16)  # Mux/rail programming remains unsupported.
    lab.pmic(0x1114, 96)  # No combined-channel request contract.
    assert lab.state()['rejected'] == before + 2
    assert lab.pmic(0x1216) == 0
    return lab.state()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', required=True, type=Path)
    parser.add_argument('--dtb', required=True, type=Path)
    args = parser.parse_args()
    qemu, dtb = args.qemu.resolve(), args.dtb.resolve()
    with tempfile.TemporaryDirectory(prefix='mt6762-thermal-qtest-') as temporary:
        lab = PowerLab(qemu, dtb, temporary, thermal=True)
        try:
            result = exercise(lab)
        finally:
            lab.close()
        lab = PowerLab(qemu, dtb, temporary)
        try:
            assert not lab.state()['thermal_enabled']
            before = lab.state()['rejected']
            assert lab.pmic(0x11ae) == 0xffff
            lab.pmic(0x110e, 16)
            assert lab.state()['rejected'] == before + 2
            assert lab.state()['thermal_requests'] == [0, 0, 0]
        finally:
            lab.close()
    bad = subprocess.run([str(qemu), '-M', 'mt6762,lab-pmic-thermal=on',
        '-accel', 'qtest', '-m', '512M', '-dtb', str(dtb), '-display', 'none',
        '-serial', 'null', '-monitor', 'none'], capture_output=True, timeout=10)
    assert bad.returncode != 0 and b'lab-power' in bad.stderr
    print(json.dumps({'passed': True, 'synthetic_only': True,
        'physical_calibration_claimed': False, 'final_state': result}, indent=2))


if __name__ == '__main__':
    main()
