#!/usr/bin/env python3
"""Read only selected display/touch metadata over an already authorized ADB.

No root, device writes, raw register reads, screen capture or event injection.
No device serial, application layer names, or unique input identifiers retained.
"""
import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adb", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"captured_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "read_only":True,"observations":[]}
    def run(command, filtering=None):
        cp = subprocess.run([str(args.adb),"shell",command], capture_output=True, timeout=30)
        stdout = cp.stdout.decode(errors="replace")
        stderr = cp.stderr.decode(errors="replace")
        if filtering:
            stdout = "\n".join(line for line in stdout.splitlines() if filtering(line))+"\n"
        evidence["observations"].append({"command":command,"returncode":cp.returncode,"stdout":stdout,"stderr":stderr})
    for event in (3,5):
        run(f"getevent -lp /dev/input/event{event}")
    for device in ("0-0038","5-003e"):
        run(f"readlink /sys/bus/i2c/devices/{device}/driver")
    for prop in ("interrupts","tpd-resolution","pinctrl-names","vtouch-supply"):
        run(f"od -An -tx1 /proc/device-tree/touch/{prop}")
    for node in ("rstoutput0","eint@0","lcm_rst_out0_gpio","lcd_bias_enp0_gpio"):
        run(f"od -An -tx1 /proc/device-tree/pinctrl@1000b000/{node}/pins_cmd_dat/pinmux")
    for prop in ("bits_per_pixel","virtual_size","stride","mode"):
        run(f"cat /sys/class/graphics/fb0/{prop}")
    run("dumpsys SurfaceFlinger", lambda s: bool(re.match(
        r"^(Current mode:|\s+activeMode=|\s+framebufferSpace=|\s+default-size=|\s+size=\[384 854\] ANativeWindow=)",s)))
    run("settings get system screen_brightness")
    run("settings get system screen_brightness_mode")
    run("dumpsys lights", lambda s: s.startswith("Service:") or bool(re.match(r"\s+Light id=0\s",s)))
    for prop in ("brightness","max_brightness"):
        run(f"cat /sys/class/leds/lcd-backlight/{prop}")
    # These are userspace compositor attributes, not physical bootloader scanout.
    evidence["limits"] = ["Compositor buffer format/stride do not prove LK scanout format/address", "DT/sysfs permission failures are preserved; no privilege escalation attempted", "No touch events recorded and no hardware controller transactions performed"]
    (args.output/"evidence.json").write_text(json.dumps(evidence,indent=2)+"\n")
    print(args.output/"evidence.json")


if __name__ == "__main__":
    main()
