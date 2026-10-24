#!/usr/bin/env python3
"""Prepare source-only inputs, run genuine Xcode15 IIG, verify generated outputs.

Never builds a kernel/userspace, installs tools, contacts or boots a phone.
All output directories/files must be new. The macOS generation path requires
validation on an actual Xcode15 host; local tests exercise guards only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile

CLASSES = sorted("IOBufferMemoryDescriptor IODMACommand IODataQueueDispatchSource "
                 "IODispatchQueue IODispatchSource IOEventLink IOInterruptDispatchSource "
                 "IOMemoryDescriptor IOMemoryMap IOService IOServiceNotificationDispatchSource "
                 "IOServiceStateNotificationDispatchSource IOUserClient IOUserServer IOWorkGroup "
                 "OSAction OSObject".split())
AVAILABILITY_COMMIT = "5d9baee345b3bc72b26c71adc65f94f2d5e9ced2"
AVAILABILITY_SHA256 = "26842f02be5cb75ab02baa6654153ed0b848ff35122a32fea3a02b8472095234"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def new_directory(path):
    path = path.absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("output already exists: " + str(path))
    path.mkdir(parents=False)
    return path.resolve()


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("missing/escaping input: " + relative)
    return path


def prepare(args):
    root = args.xnu.resolve()
    if (root / "config/MasterVersion").read_text().splitlines()[0] != "22.5.0":
        raise ValueError("expected Darwin22.5 / xnu-8796.121.2 source")
    classes = sorted(p.stem for p in (root / "iokit/DriverKit").glob("*.iig"))
    if classes != CLASSES:
        raise ValueError("expected exact17 DriverKit interfaces")
    selected = set()
    for directory in ("iokit", "osfmk", "bsd", "EXTERNAL_HEADERS"):
        for p in (root / directory).rglob("*"):
            if p.is_file() and p.suffix in (".h", ".iig"):
                selected.add(p.relative_to(root).as_posix())
    selected.update(("config/MasterVersion", "iokit/DriverKit/Makefile",
                     "makedefs/MakeInc.def", "makedefs/MakeInc.cmd",
                     "bsd/sys/make_posix_availability.sh", "bsd/sys/make_symbol_aliasing.sh"))
    for name in selected:
        checked_path(root, name)
    dependency = getattr(args, "availability_source", None)
    if dependency and digest(dependency) != AVAILABILITY_SHA256:
        raise ValueError("AvailabilityVersions source does not match pinned public revision")
    if args.archive and (args.archive.exists() or args.archive.is_symlink()):
        raise ValueError("archive already exists")
    out = new_directory(args.output)
    hashes = {}
    for name in sorted(selected):
        src = checked_path(root, name)
        dst = out / "source" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        hashes[name] = digest(dst)
    shutil.copyfile(Path(__file__).resolve(), out / "workflow.py")
    dependencies = {}
    if dependency:
        dst = out / "dependencies/AvailabilityVersions/availability.pl"
        dst.parent.mkdir(parents=True)
        shutil.copyfile(dependency, dst)
        dependencies["AvailabilityVersions/availability.pl"] = dict(
            sha256=digest(dst), commit=AVAILABILITY_COMMIT, tag="AvailabilityVersions-115.4",
            repository="https://github.com/apple-oss-distributions/AvailabilityVersions")
    try:
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        upstream = subprocess.check_output(["git", "-C", str(root), "rev-parse", "xnu-8796.121.2^{}"], text=True).strip()
    except subprocess.CalledProcessError:
        commit = upstream = None
    manifest = dict(format=1, purpose="code-generation-only", kernel_version="22.5.0",
                    upstream_tag="xnu-8796.121.2", upstream_commit=upstream,
                    checkout_commit=commit, classes=CLASSES, platform=args.platform,
                    source_sha256=hashes, workflow_sha256=digest(out / "workflow.py"),
                    dependencies=dependencies,
                    contains_sdk=False, contains_binaries=False,
                    notes="Header superset from named source directories; SDK stays on Mac. Hashes describe working files, including modifications.")
    write_json(out / "inputs.json", manifest)
    if args.archive:
        with args.archive.open("xb") as file:
            with tarfile.open(fileobj=file, mode="w:gz") as archive:
                archive.add(out, arcname=out.name, recursive=True)
    print(json.dumps(dict(bundle=str(out), files=len(hashes), input_manifest_sha256=digest(out / "inputs.json"),
                          archive=str(args.archive) if args.archive else None)))


def verify_inputs(bundle):
    bundle = bundle.resolve()
    manifest = json.loads((bundle / "inputs.json").read_text())
    if manifest.get("format") != 1 or manifest.get("classes") != CLASSES or manifest.get("kernel_version") != "22.5.0":
        raise ValueError("wrong input manifest/interface version")
    if manifest.get("platform") not in ("iPhoneOS", "MacOSX"):
        raise ValueError("unsupported deployment platform")
    if digest(bundle / "workflow.py") != manifest["workflow_sha256"]:
        raise ValueError("workflow hash changed")
    for name, expected in manifest["source_sha256"].items():
        if digest(checked_path(bundle / "source", name)) != expected:
            raise ValueError("source hash changed: " + name)
    actual = {p.relative_to(bundle / "source").as_posix() for p in (bundle / "source").rglob("*") if p.is_file()}
    if actual != set(manifest["source_sha256"]):
        raise ValueError("unexpected source inputs")
    deps = manifest.get("dependencies", {})
    actual_deps = {p.relative_to(bundle / "dependencies").as_posix()
                   for p in (bundle / "dependencies").rglob("*") if p.is_file()}
    if actual_deps != set(deps):
        raise ValueError("unexpected dependency inputs")
    for name, info in deps.items():
        if (name != "AvailabilityVersions/availability.pl" or
                info.get("commit") != AVAILABILITY_COMMIT or
                info.get("sha256") != AVAILABILITY_SHA256 or
                digest(checked_path(bundle / "dependencies", name)) != AVAILABILITY_SHA256):
            raise ValueError("unrecognized/modified public source dependency")
    return manifest


def check_xcode_version(version, diagnostic_major=None):
    if diagnostic_major not in (None, 26):
        raise ValueError("only explicit major26 diagnostic generation is supported")
    expected = diagnostic_major or 15
    if not re.search(r"^Xcode " + str(expected) + r"(?:\.|\s|$)", version, re.M):
        raise ValueError("Xcode%d required for selected mode; found %s" % (expected, version))


def generate(args):
    if platform.system() != "Darwin":
        raise ValueError("generation requires macOS with genuine Xcode15")
    bundle = args.bundle.resolve()
    manifest = verify_inputs(bundle)
    developer = args.xcode.resolve() / "Contents/Developer"
    if not developer.is_dir():
        raise ValueError("--xcode must point to an existing Xcode.app")
    env = os.environ.copy()
    env["DEVELOPER_DIR"] = str(developer)
    env.pop("DRIVERKITROOT", None)
    def capture(command):
        return subprocess.check_output(command, env=env, text=True, stderr=subprocess.STDOUT).strip()
    version = capture(["/usr/bin/xcodebuild", "-version"])
    diagnostic_major = args.diagnostic_xcode_major
    check_xcode_version(version, diagnostic_major)
    sdk = Path(capture(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"])).resolve()
    iig = Path(capture(["/usr/bin/xcrun", "--sdk", "macosx", "--find", "iig"])).resolve()
    if not iig.is_relative_to(developer) or not os.access(iig, os.X_OK):
        raise ValueError("IIG must be executable inside selected Xcode")
    if iig.read_bytes()[:4] not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf"):
        raise ValueError("IIG is not a Mach-O executable; refusing shim")
    availability = sdk / "usr/local/libexec/availability.pl"
    bundled_availability = "AvailabilityVersions/availability.pl" in manifest.get("dependencies", {})
    if bundled_availability:
        availability = bundle / "dependencies/AvailabilityVersions/availability.pl"
    elif not availability.is_file() or not os.access(availability, os.X_OK):
        raise ValueError("SDK availability.pl missing; prepare with pinned --availability-source")
    out = new_directory(args.output)
    generated = out / "DriverKit"
    generated.mkdir()
    support = out / "support/bsd/sys"
    support.mkdir(parents=True)
    source = bundle / "source"
    report = dict(format=1, status="running", code_generation_only=True,
                  inputs_sha256=digest(bundle / "inputs.json"), classes=CLASSES,
                  xcode_version=version, developer_dir=str(developer), sdk=str(sdk),
                  iig_path=str(iig), iig_sha256=digest(iig), availability_sha256=digest(availability),
                  platform=manifest["platform"], commands=[], outputs={})
    report["diagnostic_xcode_major"] = diagnostic_major
    report["dependencies"] = manifest.get("dependencies", {})
    def execute(command, label):
        report["commands"].append(command)
        with (out / (label + ".log")).open("x") as log:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
    try:
        signature_command = ["/usr/bin/codesign", "--verify", "--strict", "-R=anchor apple", str(iig)]
        execute(signature_command, "iig-codesign-verify")
        execute(["/usr/bin/codesign", "-d", "--verbose=4", str(iig)], "iig-codesign-details")
        report["iig_codesign"] = dict(verified=True, apple_anchor=True,
            command=signature_command, details_log="iig-codesign-details.log")
        report["iig_version"] = capture([str(iig), "--version"])
        alias_sdk = sdk
        if bundled_availability:
            alias_sdk = out / "support/sdk"
            staged = alias_sdk / "usr/local/libexec/availability.pl"
            staged.parent.mkdir(parents=True)
            shutil.copyfile(availability, staged)
            staged.chmod(0o755)
        report["alias_sdk"] = str(alias_sdk)
        execute(["/bin/sh", str(source / "bsd/sys/make_posix_availability.sh"), str(support / "_posix_availability.h")], "prepare-posix")
        execute(["/bin/bash", str(source / "bsd/sys/make_symbol_aliasing.sh"), str(alias_sdk), str(support / "_symbol_aliasing.h")], "prepare-aliases")
        flags = ["-I" + str(source / name) for name in ("iokit", "osfmk", "bsd")]
        flags += ["-I" + str(out / "support/bsd"), "-I" + str(source / "EXTERNAL_HEADERS"),
                  "-isysroot", str(sdk), "-x", "c++", "-std=gnu++1z", "-D__IIG=1",
                  "-DDRIVERKIT_PRIVATE=1", "-DPRIVATE_WIFI_ONLY=1", "-DXNU_PLATFORM_" + manifest["platform"]]
        for cls in CLASSES:
            execute([str(iig), "--def", str(source / "iokit/DriverKit" / (cls + ".iig")),
                     "--header", str(generated / (cls + ".h")), "--impl", str(generated / (cls + ".iig.cpp")),
                     "--framework-name", "DriverKit", "--"] + flags, cls)
        verify_inputs(bundle)  # Generation must not mutate any bundled input.
        report["outputs"] = inspect_outputs(generated, diagnostic=bool(diagnostic_major),
                                             source=source / "iokit/DriverKit")
        report["kernelContent_occurrences"] = {p.name: p.read_text().count("kernelContent")
            for p in sorted(generated.iterdir()) if "kernelContent" in p.read_text()}
        report["support_sha256"] = {p.name: digest(p) for p in support.glob("*.h")}
        report["status"] = ("diagnostic-generated-not-compatible" if diagnostic_major else
                            "generated-structurally-verified-not-compiled")
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        write_json(out / "generation.json", report)
    print(json.dumps(dict(output=str(out), status=report["status"], files=len(report["outputs"]))))


def inspect_outputs(directory, diagnostic=False, source=None):
    expected = {c + suffix for c in CLASSES for suffix in (".h", ".iig.cpp")}
    actual = {p.name for p in directory.iterdir()}
    if actual != expected:
        raise ValueError("generated output must contain exactly17 header/implementation pairs")
    hashes = {}
    for name in sorted(expected):
        path = checked_path(directory, name)
        text = path.read_text()
        markers = ("iig shim", "gen-iig-stubs.py", "__iig_stub_") + (() if diagnostic else ("kernelContent",))
        if len(text) < 256 or any(s in text for s in markers):
            raise ValueError("empty/shim/incompatible generated output: " + name)
        if name.endswith(".iig.cpp") and "IORPC" not in text:
            raise ValueError("generated implementation has no RPC content: " + name)
        hashes[name] = digest(path)
    for cls in CLASSES:
        header, cpp = [re.sub(r"/\*.*?\*/|//[^\n]*", "", (directory / (cls + suffix)).read_text(), flags=re.S)
                       for suffix in (".h", ".iig.cpp")]
        invokes = set(re.findall(r"\b(\w+_Invoke)\s*\(", header))
        if not invokes:
            raise ValueError("no class RPC Invoke declarations: " + cls)
        original = (re.sub(r"/\*.*?\*/|//[^\n]*", "", (source / (cls + ".iig")).read_text(), flags=re.S)
                    if source is not None else "")
        def defined(method):
            return bool(re.search(r"\b" + re.escape(cls + "::" + method) + r"\s*\([^;{}]*\)\s*\{", cpp, re.S))
        for invoke in invokes:
            if not defined(invoke):
                raise ValueError("missing class RPC definition: " + cls + "::" + invoke)
            base = invoke.removesuffix("_Invoke")
            local_pattern = r"\b" + re.escape(base) + r"\s*\([^;{}]*\)\s*LOCAL\s*;"
            local_call = (re.search(local_pattern, original, re.S) and
                          re.search(local_pattern, header, re.S) and
                          re.search(r"\b" + re.escape(base + "_Call") + r"\s*\(", header) and
                          defined(base + "_Call"))
            if not defined(base) and not local_call:
                raise ValueError("missing class RPC wrapper: " + cls + "::" + base)
    return hashes


def verify(args):
    manifest = verify_inputs(args.bundle)
    output = args.output.resolve()
    report = json.loads((output / "generation.json").read_text())
    if report.get("status") != "generated-structurally-verified-not-compiled" or report.get("classes") != CLASSES:
        raise ValueError("generation did not complete")
    check_xcode_version(report.get("xcode_version", ""))
    if report.get("diagnostic_xcode_major") is not None or report.get("iig_codesign", {}).get("verified") is not True or report.get("iig_codesign", {}).get("apple_anchor") is not True:
        raise ValueError("diagnostic or unverified generator is not eligible")
    if report["inputs_sha256"] != digest(args.bundle / "inputs.json") or report["platform"] != manifest["platform"]:
        raise ValueError("generation inputs do not match bundle")
    if inspect_outputs(output / "DriverKit", source=args.bundle / "source/iokit/DriverKit") != report["outputs"]:
        raise ValueError("generated output hashes changed")
    print("PASS: input/output hashes and17pairs; compile/export/RPC behavior remain unvalidated")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    q = sub.add_parser("prepare")
    q.add_argument("--xnu", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    q.add_argument("--archive", type=Path)
    q.add_argument("--platform", choices=("iPhoneOS", "MacOSX"), required=True)
    q.add_argument("--availability-source", type=Path)
    q.set_defaults(run=prepare)
    q = sub.add_parser("generate")
    q.add_argument("--bundle", type=Path, required=True)
    q.add_argument("--xcode", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    q.add_argument("--diagnostic-xcode-major", type=int, choices=(26,))
    q.set_defaults(run=generate)
    q = sub.add_parser("verify")
    q.add_argument("--bundle", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    q.set_defaults(run=verify)
    args = p.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
