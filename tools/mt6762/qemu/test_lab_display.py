#!/usr/bin/env python3
"""QEMU-only register/PWM fixture tests. Never connects to a physical device.

Requires the local MT6762 QEMU patch series and an explicit research DTB.
The CPU remains paused; qtest accesses synthetic MMIO and QMP injects faults.
This does not establish DSI scanout, actual brightness or panel behaviour.
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time


class Lab:
    def __init__(self, qemu, dtb, directory, enabled=True, accel='tcg', two_layer=False):
        directory = Path(directory)
        self.log = (directory / "qemu.log").open("w+")
        self.qmp_path = directory / "qmp.sock"
        self.test_path = directory / "qtest.sock"
        machine = "mt6762,lab-i2c=on"
        self.two_layer = two_layer
        if enabled:
            machine += ",lab-display=on,lab-display-fb=" + (
                "0x7ef90000,lab-display-two-layer=on" if two_layer else "0x41000000")
        self.process = subprocess.Popen([
            str(qemu), "-M", machine, "-accel", accel, "-cpu", "cortex-a53",
            "-m", "1024M" if two_layer else "512M", "-smp", "1", "-dtb", str(dtb),
            *([] if accel == 'qtest' else ['-S']),
            "-display", "none", "-serial", "null", "-monitor", "none",
            "-qmp", f"unix:{self.qmp_path},server=on,wait=off",
            "-qtest", f"unix:{self.test_path},server=on,wait=off",
        ], stdout=self.log, stderr=self.log)
        self.sockets = []
        try:
            self.qmp = self.connect(self.qmp_path)
            self.test = self.connect(self.test_path)
            assert "QMP" in json.loads(self.qmp.readline())
            self.command("qmp_capabilities")
        except BaseException:
            self.close()
            raise

    def connect(self, path):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.log.seek(0)
                raise RuntimeError(self.log.read())
            sock = socket.socket(socket.AF_UNIX)
            sock.settimeout(5)
            try:
                sock.connect(str(path))
            except (FileNotFoundError, ConnectionRefusedError):
                sock.close()
                time.sleep(0.02)
                continue
            self.sockets.append(sock)
            return sock.makefile("rwb", buffering=0)
        raise TimeoutError(f"QEMU socket {path.name} did not appear")

    def command(self, command, **arguments):
        self.qmp.write((json.dumps({"execute": command, "arguments": arguments}) + "\n").encode())
        while True:
            answer = json.loads(self.qmp.readline())
            if "event" in answer:
                continue
            if "error" in answer:
                raise RuntimeError(answer["error"])
            return answer.get("return")

    def state(self):
        return json.loads(self.command("qom-get", path="/machine", property="lab-display-state"))

    def fault(self, name):
        self.command("qom-set", path="/machine", property="lab-display-fault", value=name)

    def access(self, text):
        self.test.write((text + "\n").encode())
        reply = self.test.readline().decode().strip()
        if not reply.startswith("OK"):
            raise RuntimeError(reply)
        return reply[2:].strip()

    def read(self, address):
        return int(self.access(f"readl {address:#x}"), 0)

    def write(self, address, value):
        self.access(f"writel {address:#x} {value:#x}")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for name in ["qmp", "test"]:
            stream = getattr(self, name, None)
            if stream:
                stream.close()
        for sock in self.sockets:
            sock.close()
        self.log.close()


def exercise(lab):
    base=0x7ef90000 if lab.two_layer else 0x41000000
    initial=1023 if lab.two_layer else 512
    assert lab.state()["applied_level"] == initial
    assert lab.read(0x1400bf40) == base
    assert lab.read(0x10006180) == lab.read(0x10006184) == 8
    assert lab.read(0x10000080) == (0x30101 if lab.two_layer else 0x03000000)
    if lab.two_layer:
        assert lab.read(0x10005350) == 0x11111441
        assert lab.read(0x1400bf60) == base+0x144000
        assert lab.read(0x1400b02c) == 3
        assert lab.read(0x1400b024) == 0x81000001
    assert not lab.read(0x100010ac) & 4
    assert lab.read(0x1401401c) == (0x2c030480 if lab.two_layer else (3 << 16) | 1152)
    if not lab.two_layer:
        assert not lab.state()["two_layer"]
        assert lab.read(0x1400b02c) == 1 and lab.read(0x1400b030) == 0x20ff
        assert lab.read(0x1400bf60) == lab.read(0x1400b050) == 0
        before = lab.state()['reads']['ovl']
        assert lab.read(0x1400b024) == lab.read(0x1400b3a0) == 0
        assert lab.state()['reads']['ovl'] == before + 2
        before = lab.state()['rejected_writes']
        lab.write(0x1400b024, 0xffffffff)
        lab.write(0x1400b3a0, 0xffffffff)
        assert lab.read(0x1400b024) == lab.read(0x1400b3a0) == 0
        assert lab.state()['rejected_writes'] == before + 2
    pwm = 0x1100e000
    assert lab.read(pwm + 0x18) == (0 if lab.two_layer else 3 << 16)
    assert lab.read(pwm + 0x1c) == (initial << 16) | 1023
    lab.write(pwm + 0x1c, (700 << 16) | 1023)
    lab.write(pwm, 1)
    assert lab.state()["applied_level"] == initial
    lab.write(pwm + 0xc, 1)
    assert lab.state()["applied_level"] == initial
    lab.write(pwm + 0xc, 0)
    assert lab.state()["applied_level"] == 700 and lab.state()["commits"] == 1
    lab.write(pwm + 0xc, 0)  # No rising edge: no new latch.
    assert lab.state()["commits"] == 1
    lab.write(pwm + 0x1c, (1 << 16) | 1023)
    lab.write(pwm, 0)
    lab.write(pwm + 0xc, 1)
    lab.write(pwm + 0xc, 0)
    assert lab.state()["applied_level"] == 0 and lab.state()["commits"] == 2
    lab.fault("pwm-drop")
    lab.write(pwm + 0x1c, (900 << 16) | 1023)
    lab.write(pwm, 1)
    lab.write(pwm + 0xc, 1)
    lab.write(pwm + 0xc, 0)
    assert lab.read(pwm + 0x1c) == (1 << 16) | 1023
    assert lab.state()["applied_level"] == 0 and lab.state()["commits"] == 2
    lab.fault("power-off")
    assert lab.read(0x10006180) == 0 and lab.read(0x10006184) == 0
    lab.fault("scanout-mismatch")
    assert lab.read(0x1400bf40) != base
    lab.fault("none")
    lab.write(0x1400bf40, 0x43000000)  # Pipeline is inherited, not programmable.
    assert lab.read(0x1400bf40) == base
    before = lab.state()["rejected_writes"]
    lab.write(pwm + 0x1c, (1024 << 16) | 1023)
    lab.write(pwm + 0xc, 1)
    lab.write(pwm + 0xc, 0)
    assert lab.state()["rejected_writes"] == before + 1
    assert lab.state()["commits"] == 2
    return lab.state()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--dtb", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mt6762-display-qtest-") as temporary:
        lab = Lab(args.qemu.resolve(), args.dtb.resolve(), temporary)
        try:
            result = exercise(lab)
        finally:
            lab.close()
        lab = Lab(args.qemu.resolve(), args.dtb.resolve(), temporary, two_layer=True)
        try:
            assert lab.state()["two_layer"]
            registers = {
                0x1400b00c: 1, 0x1400b02c: 3, 0x1400b020: 384 | (854 << 16),
                0x1400b030: 0x21ff, 0x1400b050: 0x21ff,
                0x1400b038: 384 | (854 << 16), 0x1400b058: 384 | (854 << 16),
                0x1400b044: 1536, 0x1400b064: 1536,
                0x1400bf40: 0x7ef90000, 0x1400bf60: 0x7f0d4000,
                0x1400b03c: 0, 0x1400b05c: 0, 0x1400b04c: 0, 0x1400b06c: 0,
                0x1400b324: 0, 0x1400b024: 0x81000001, 0x1400b3a0: 0,
                0x1400b0c0: 0x520001, 0x1400b0e0: 0x480001,
                0x1400d010: 0x101, 0x14014000: 1, 0x14014014: 2,
                0x14014018: 0x1001c, 0x1401401c: 0x2c030480,
                0x14014020: 2, 0x14014024: 20, 0x14014028: 170, 0x1401402c: 854,
            }
            before = lab.state()['reads']['ovl']
            assert {a: lab.read(a) for a in registers} == registers
            assert lab.state()['reads']['ovl'] == before + sum(
                0x1400b000 <= a < 0x1400c000 for a in registers)
            before = lab.state()["rejected_writes"]
            for address, value in registers.items():
                lab.write(address, value ^ 0xffffffff)
            assert {a: lab.read(a) for a in registers} == registers
            assert lab.state()["rejected_writes"] == before + len(registers)
            try:
                lab.command('qom-set', path='/machine', property='lab-display-two-layer', value=False)
                raise AssertionError('fixture mode must be immutable')
            except RuntimeError as error:
                assert 'before initialization' in str(error)
            lab.fault('scanout-mismatch')
            assert lab.read(0x1400bf40) == 0x7ef94000
            assert lab.read(0x1400bf60) == 0x7f0d8000
            lab.fault('none')
            assert {a: lab.read(a) for a in registers} == registers
            lk_result = exercise(lab)
        finally:
            lab.close()
        lab = Lab(args.qemu.resolve(), args.dtb.resolve(), temporary, enabled=False)
        try:
            assert lab.state() == {"enabled": False}
            assert lab.read(0x1100e018) == 0
        finally:
            lab.close()
    # Board must reject invalid physical-range assertions before mapping any
    # display registers. The4GiB case uses RAM spanning that boundary so it
    # exercises the narrower32-bit scanout limit, not merely the RAM bound.
    for options, memory in [
        ("lab-display=on,lab-display-fb=0x41000000", "512M"),
        ("lab-i2c=on,lab-display=on,lab-display-fb=0x41000001", "512M"),
        ("lab-i2c=on,lab-display=on,lab-display-fb=0x3fff0000", "512M"),
        ("lab-i2c=on,lab-display=on,lab-display-fb=0x5fff0000", "512M"),
        ("lab-i2c=on,lab-display=on,lab-display-fb=0xffffc000", "4096M"),
    ]:
        failed = subprocess.run([
            str(args.qemu.resolve()), "-M", "mt6762," + options, "-m", memory,
            "-accel", "tcg", "-smp", "1", "-dtb", str(args.dtb.resolve()),
            "-S", "-display", "none", "-serial", "null", "-monitor", "none",
        ], capture_output=True, timeout=10)
        assert failed.returncode != 0 and b"lab-display requires" in failed.stderr, failed.stderr
    for options, memory in [
        ('lab-display-two-layer=on', '1024M'),
        ('lab-i2c=on,lab-display=on,lab-display-two-layer=on,lab-display-fb=0x41000000', '1024M'),
        ('lab-i2c=on,lab-display=on,lab-display-two-layer=on,lab-display-fb=0x7ef90000', '512M'),
        ('lab-i2c=on,lab-display=on,lab-display-two-layer=on,lab-display-fb=0x7ef90000', '1010M'),
    ]:
        failed = subprocess.run([
            str(args.qemu.resolve()), '-M', 'mt6762,' + options, '-m', memory,
            '-accel', 'tcg', '-smp', '1', '-dtb', str(args.dtb.resolve()),
            '-S', '-display', 'none', '-serial', 'null', '-monitor', 'none',
        ], capture_output=True, timeout=10)
        assert failed.returncode != 0 and b'lab-display-two-layer requires' in failed.stderr
    print(json.dumps({"synthetic_only": True, "passed": True, "final_fixture_state": result,
                      "lk_fixture_state": lk_result}, indent=2))


if __name__ == "__main__":
    main()
