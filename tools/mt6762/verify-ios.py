#!/usr/bin/env python3
"""Read-only comparison of extracted Apple binaries with the generated APFS image.

This verifies byte preservation, not successful boot or filesystem completeness.
The pinned donor APFS reader is used to read the generated image without mounting it.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("runtime", type=Path)
parser.add_argument("--sources-only", action="store_true",
                    help="Hash extracted originals before the staging/build step")
parser.add_argument("--baseline", type=Path,
                    help="Require originals to match a pre-build --sources-only report")
parser.add_argument("--system-image", type=Path,
                    help="Verify a captured experiment image instead of runtime/userland/system.apfs")
parser.add_argument("--root-image", type=Path,
                    help="Verify a captured experiment image instead of runtime/userland/root.apfs")
args = parser.parse_args()
runtime = args.runtime.resolve()
ios = runtime / "ios165"
critical = {
    "sbin/launchd": "/sbin/launchd.ios",
    "usr/lib/dyld": "/usr/lib/dyld",
    "System/Library/CoreServices/SpringBoard.app/SpringBoard":
        "/System/Library/CoreServices/SpringBoard.app/SpringBoard",
}


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path):
    st = path.stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


files = [(ios / "rootfs" / name, dest) for name, dest in critical.items()]
cache = ios / "20F66__iPhone10,3_6"
cache_files = sorted(p for p in cache.iterdir()
                     if re.fullmatch(r"dyld_shared_cache_arm64(?:\.\d+(?:\.dylddata|\.dyldlinkedit)?)?", p.name))
if len(cache_files) != 43:
    raise SystemExit(f"Expected 43 mapped cache files, found {len(cache_files)}")
cache_destination = "/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld/"
files += [(p, cache_destination + p.name) for p in cache_files]
originals = []
for path, destination in files:
    before = identity(path)
    sha = sha_file(path)
    if identity(path) != before:
        raise SystemExit(f"Source changed while being read: {path}")
    originals.append({"source": str(path.relative_to(runtime)), "destination": destination,
                      "size": path.stat().st_size, "sha256": sha})
if args.baseline:
    baseline = json.loads(args.baseline.read_text())
    if baseline["originals"] != originals:
        raise SystemExit("Extracted Apple originals changed since the pre-build snapshot")
if args.sources_only:
    print(json.dumps({"originals": originals, "cache_files": len(cache_files)}, indent=2))
    raise SystemExit(0)

# The reader is an upstream source file, not a binary taken from the IPSW.
sys.path.insert(0, str(runtime / "tools/apfs"))
import apfs

system = args.system_image or runtime / "userland/system.apfs"
root = args.root_image or runtime / "userland/root.apfs"
system_before, root_before = identity(system), identity(root)
container = apfs.Container(str(system))
volume = apfs.pick_volume(container, None)
matches = []


def image_sha(vol, path):
    entry = vol.lookup(path)
    if entry is None:
        raise ValueError(f"Missing image member {path}")
    data = vol.inode(entry[0]).contents()
    return len(data), hashlib.sha256(data).hexdigest()


try:
    for original in originals:
        size, sha = image_sha(volume, original["destination"])
        if (size, sha) != (original["size"], original["sha256"]):
            raise ValueError(f"Apple bytes differ in image: {original['destination']}")
        matches.append(original)
    _, stage0_sha = image_sha(volume, "/sbin/launchd")
    if stage0_sha != sha_file(runtime / "userland/obj/stage0"):
        raise ValueError("The image's stage0 does not match the locally built project helper")
finally:
    container.close()
container = apfs.Container(str(root))
try:
    _, init_sha = image_sha(apfs.pick_volume(container, None), "/sbin/init")
    if init_sha != sha_file(runtime / "userland/obj/init"):
        raise ValueError("The small image's init does not match the locally built project helper")
finally:
    container.close()

# When KEEP=1 retained Apple's filesystem DMG, independently compare the three
# critical executable files against that source, not just the extracted tree.
dmg_checks = []
dmg = ios / "rootfs.dmg"
if dmg.is_file():
    for source in critical:
        result = subprocess.run(["7z", "x", "-so", str(dmg), source],
                                capture_output=True, check=True)
        sha = hashlib.sha256(result.stdout).hexdigest()
        if not result.stdout or sha != sha_file(ios / "rootfs" / source):
            raise ValueError(f"Extracted executable differs from Apple DMG: {source}")
        dmg_checks.append(source)
if identity(system) != system_before or identity(root) != root_before:
    raise SystemExit("An APFS image changed during verification; result is invalid")
print(json.dumps({
    "status": "verified-byte-preservation",
    "read_only": True,
    "apple_executables_recompiled": False,
    "critical_executables_checked": len(critical),
    "critical_executables_checked_against_retained_apple_dmg": len(dmg_checks),
    "mapped_cache_files_checked": len(cache_files),
    "system_image_bytes": system.stat().st_size,
    "root_image_bytes": root.stat().st_size,
    "system_image": str(system.resolve()), "root_image": str(root.resolve()),
    "project_stage0_matches": True, "project_init_matches": True,
    "resources_are_unmodified": False,
    "resource_changes": "Donor fetch recipe trims AppleColorEmoji and PingFang fonts; build selects/rearranges resources and launch jobs.",
    "limit": "Checks extracted Apple cache files against APFS bytes and three executables against the retained Apple DMG when available; does not establish boot, authenticity, or all-file preservation.",
    "originals": matches,
}, indent=2))
