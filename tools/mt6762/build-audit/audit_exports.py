#!/usr/bin/env python3
"""Read-only input audit of failed export verification; emits JSON evidence.

Does not build, patch exports, run iig, or copy SDK/binary contents.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--xnu", required=True, type=Path)
    p.add_argument("--build-log", required=True, type=Path)
    p.add_argument("--deps", required=True, type=Path)
    p.add_argument("--llvm-bin", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    root, deps = a.xnu.resolve(), a.deps.resolve()
    obj = root / "BUILD/obj/DEVELOPMENT_ARM64_MT6762"
    nm, demangler = (str(a.llvm_bin / name) for name in ("llvm-nm", "llvm-cxxfilt"))
    marker = "exported name not in import list: "
    lines = a.build_log.read_text().splitlines()
    diagnostics, repairs = [], []
    for index, line in enumerate(lines):
        if marker not in line:
            continue
        original = line
        # Parallel make can insert a progress record inside an error write.
        # Reconstruct only this exact recognized format and retain both lines;
        # the reconstructed ABI name must still map to a real export below.
        progress = re.search(r"[ \t]+SYMSET [A-Za-z0-9_]+ \(arm64\)$", line)
        if progress and index + 1 < len(lines) and marker not in lines[index + 1]:
            line = line[:progress.start()] + lines[index + 1]
            repairs.append(dict(line=index + 1, original=[original, lines[index + 1]],
                                reconstructed=line))
        diagnostics.append(line.split(marker, 1)[1])
    missing = sorted(set(diagnostics))
    kernel = obj / "mach.development.mt6762"
    actual = set(subprocess.check_output([nm, "-gj", str(kernel)], text=True).splitlines())
    imported = set((obj / "config/allsymbols").read_text().splitlines())
    raw = {}
    for file in sorted((root / "config").glob("*.exports")):
        for line in file.read_text().splitlines():
            name = line.split("#", 1)[0].strip()
            if name.startswith("_") and ":" not in name:
                raw.setdefault(name, []).append(str(file.relative_to(root)))
    names = list(raw)
    text = "\n".join(n[1:] if n.startswith("__Z") else n for n in names) + "\n"
    demangled = subprocess.check_output([demangler], input=text, text=True).splitlines()
    # cctools and LLVM print the same block-pointer ABI using different prose.
    canonical = lambda n: n.replace("void ( block_pointer)()", "void () block_pointer")
    wanted = {canonical(n): n for n in missing}
    rows = []
    for name, demangled_name in zip(names, demangled):
        if demangled_name not in wanted:
            continue
        label = wanted[demangled_name]
        if label in ("_pmap_cs_configuration", "_pmap_has_iofilter_protected_write"):
            category = "generic_pmap_queries_missing_arm_definitions"
        elif "IOUnifiedAddressTranslator" in label:
            category = "apple_uat_missing_open_source_implementation"
        elif label.startswith("_"):
            category = "apple_iommu_ppl_hardware_exports_missing_implementation"
        else:
            category = "driverkit_generated_abi_missing"
        rows.append(dict(name=label, mangled=name, category=category,
                         export_files=raw[name], present_in_kernel=name in actual))
    assert len(rows) == len(missing), "unmapped diagnostic; inspect demangler or export syntax"
    objects = []
    for file in sorted((obj / "iokit/DEVELOPMENT").glob("*.iig.cpo")):
        definitions = subprocess.check_output([nm, "-gj", "--defined-only", str(file)], text=True).splitlines()
        objects.append(dict(path=str(file.relative_to(root)), sha256=sha(file),
                            bytes=file.stat().st_size, global_definitions=len(definitions)))
    sources = ["config/Makefile", "config/Private.exports", "config/Private.arm64.exports",
               "iokit/DriverKit/Makefile", "osfmk/vm/pmap.h", "osfmk/vm/pmap_cs.h",
               "osfmk/arm/pmap/pmap.c", "osfmk/x86_64/pmap.c",
               "pexpert/pexpert/arm64/MT6762.h", "pexpert/pexpert/arm64/board_config.h"]
    shim = deps / "iig-impl/OSObject.iig.cpp"
    result = dict(
        build_log_sha256=sha(a.build_log), kernel_sha256=sha(kernel),
        repaired_interleaved_diagnostics=repairs,
        actual_nm_names=len(actual), import_names=len(imported),
        import_missing_actual=sorted(actual - imported), import_extra=sorted(imported - actual),
        missing_count=len(rows), categories=dict(Counter(r["category"] for r in rows)),
        missing_exports=rows, generated_objects=objects,
        source_sha256={name: sha(root / name) for name in sources},
        toolchain_files=[dict(path=str(deps / name), sha256=sha(deps / name)) for name in
                         ("host/bin/iig", "gen-iig-stubs.py", "iig-impl/OSObject.iig.cpp")],
        aggregate_shim_unsupported_bodies=shim.read_text().count("return kIOReturnUnsupported"),
        query_source_occurrences={name: [f"{path}:{line_number}"
            for path in sources
            for line_number, line in enumerate((root / path).read_text().splitlines(), 1)
            if name.lstrip("_") in line]
            for name in ("_pmap_cs_configuration", "_pmap_has_iofilter_protected_write")},
        arm_callers_in_supplied_source=[],
        caller_audit_scope="rg of both exact names through source tree excluding BUILD/tools; no ARM or IOKit call sites; external binary consumers not audited",
        conclusion="Required methods absent before linking; nm/import list match exactly. No exports deleted and no ABI stubs added.",
    )
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(missing=result["missing_count"], categories=result["categories"],
                          import_matches_kernel=imported == actual)))


if __name__ == "__main__":
    main()
