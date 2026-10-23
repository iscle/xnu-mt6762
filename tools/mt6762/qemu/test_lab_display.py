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
    def __init__(self, qemu, dtb, directory, enabled=True, accel='tcg'):
        directory = Path(directory)
        self.log = (directory / "qemu.log").open("w+")
        self.qmp_path = directory / "qmp.sock"
        self.test_path = directory / "qtest.sock"
        machine = "mt6762,lab-i2c=on"
        if enabled:
            machine += ",lab-display=on,lab-display-fb=0x41000000"
        self.process = subprocess.Popen([
            str(qemu), "-M", machine, "-accel", accel, "-cpu", "cortex-a53",
            "-m", "512M", "-smp", "1", "-dtb", str(dtb),
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
    assert lab.state()["applied_level"] == 512
    assert lab.read(0x1400bf40) == 0x41000000
    assert lab.read(0x10006180) == lab.read(0x10006184) == 8
    assert lab.read(0x10000080) == 0x03000000
    assert not lab.read(0x100010ac) & 4
    assert lab.read(0x1401401c) == (2 << 16) | 1152
    pwm = 0x1100e000
    assert lab.read(pwm + 0x18) == 3 << 16
    assert lab.read(pwm + 0x1c) == (512 << 16) | 1023
    lab.write(pwm + 0x1c, (700 << 16) | 1023)
    lab.write(pwm, 1)
    assert lab.state()["applied_level"] == 512
    lab.write(pwm + 0xc, 1)
    assert lab.state()["applied_level"] == 512
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
    assert lab.read(0x1400bf40) != 0x41000000
    lab.fault("none")
    lab.write(0x1400bf40, 0x43000000)  # Pipeline is inherited, not programmable.
    assert lab.read(0x1400bf40) == 0x41000000
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
    print(json.dumps({"synthetic_only": True, "passed": True, "final_fixture_state": result}, indent=2))


if __name__ == "__main__":
    main()
