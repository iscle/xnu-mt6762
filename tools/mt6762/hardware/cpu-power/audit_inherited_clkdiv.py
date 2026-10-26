#!/usr/bin/env python3
"""Bounded offline replay of exact stock CKDIV0 handling and capture26 inputs.

Requires existing Capstone/Unicorn. No phone access or hardware emulation.
The preloader replay models register storage, not the electrical clock tree.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import capstone
from unicorn import Uc, UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R2, UC_ARM_REG_PC
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC

from decode_clock_snapshot import decode_snapshot, DOMAINS

IMAGE_SHA = "82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b"
PRELOADER_SHA = "7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674"


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image", "preloader", "capture", "bsp", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    image, preloader = args.image.read_bytes(), args.preloader.read_bytes()
    if sha(image) != IMAGE_SHA or sha(preloader) != PRELOADER_SHA:
        parser.error("unsupported exact stock Image/preloader")
    args.output.mkdir(parents=True, exist_ok=True)
    json_blob = (args.capture / "peripherals-result.json").read_bytes()
    capture = json.loads(json_blob)
    raw = (args.capture / "peripherals.bin").read_bytes()
    if len(raw) != 4096 or raw[:16] != struct.pack("<8sII", b"MTKPER01", 2, 4096):
        parser.error("expected complete version2 passive record")
    if capture["sha256"] != sha(raw) or struct.unpack_from("<4I", raw, 48) != (2, 0xFFFFFFFD, 2, len(capture["registers"]) - 1):
        parser.error("capture hash/completion mismatch")
    for index, entry in enumerate(capture["registers"]):
        expected = (int(entry["address"], 0), entry["width"], entry["group"],
                    entry["valid"], entry["first"], entry["second"])
        if struct.unpack_from("<IBBHII", raw, 96 + 16 * index) != expected:
            parser.error("raw register record differs from JSON")
    configured = decode_snapshot(capture)
    if not all(domain["valid"] and domain["fields"]["ckdiv_code"] == 0
               for domain in configured["domains"].values()):
        parser.error("expected stable inherited CKDIV0 samples")

    # Original Thumb code changes only the PLL source bits, preserving DIVSEL.
    # R2=1 is set by the original MOVS at VA0x2245d4, just before this slice.
    pl_base, pl_start, pl_end = 0x200710, 0x2245DE, 0x2245F8
    assert preloader[0x2245D4 - pl_base:0x2245D6 - pl_base] == bytes.fromhex("0122")
    assert struct.unpack_from("<I", preloader, 0x22466C - pl_base)[0] == 0x1000C000
    boot_literals = []
    for domain, address in (("cpu0_3", 0x224674), ("cpu4_7", 0x224670), ("cci", 0x224678)):
        word = struct.unpack_from("<I", preloader, address - pl_base)[0]
        observed = int(configured["domains"][domain]["registers"]["con1"]["value"], 0)
        assert word & 0x7FFFFFFF == observed & 0x7FFFFFFF
        boot_literals.append(dict(domain=domain, literal_va=hex(address), word=hex(word),
                                  matches_capture_excluding_update_bit=True))
    machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    machine.mem_map(0x200000, (len(preloader) + 0x710 + 4095) & ~4095)
    machine.mem_write(pl_base, preloader)
    machine.mem_map(0x10200000, 0x1000)
    preloader_cases = []
    for selector in range(32):
        before = [(selector << 17) | 0x10800, (selector << 17) | 0x8FF,
                  (selector << 17) | 0x10800]
        for addresses, value in zip(DOMAINS.values(), before):
            machine.mem_write(addresses[3], struct.pack("<I", value))
        machine.reg_write(UC_ARM_REG_R2, 1)
        machine.emu_start(pl_start | 1, pl_end, count=32)
        assert machine.reg_read(UC_ARM_REG_PC) == pl_end
        after = [struct.unpack("<I", machine.mem_read(addresses[3], 4))[0]
                 for addresses in DOMAINS.values()]
        assert after == [(value & ~(3 << 9)) | (1 << 9) for value in before]
        preloader_cases.append(dict(divsel=selector, before=list(map(hex, before)),
                                    after=list(map(hex, after))))

    # Execute the actual stock getter with the captured register values.
    image_base, function, function_end = 0xFFFFFF8008080000, 0xFFFFFF800867BCF0, 0xFFFFFF800867BE60
    getter = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    getter.mem_map(image_base, 0x2000000)
    getter.mem_write(image_base, image)
    getter.mem_map(0x100000, 0x10000)
    getter.mem_write(0x100010, struct.pack("<Q", 0x101000))
    getter.mem_write(0x100020, struct.pack("<Q", 0x101004))
    getter.mem_write(0xFFFFFF80099CB768, bytes(4))  # stock diagnostic verbosity

    def hook(uc, address, size, unused):
        if address == 0xFFFFFF800809EF9C:
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif not function <= address < function_end:
            raise RuntimeError(f"unexpected execution at {address:#x}")

    getter.hook_add(UC_HOOK_CODE, hook)
    stock_cases = []
    for domain, result in configured["domains"].items():
        registers = {key: int(value["value"], 0) for key, value in result["registers"].items()}
        getter.mem_write(0x101000, struct.pack("<II", registers["con1"], registers["ckdiv"]))
        getter.reg_write(UC_ARM64_REG_X0, 0x100000)
        getter.reg_write(UC_ARM64_REG_SP, 0x10F000)
        getter.reg_write(UC_ARM64_REG_LR, 0x200000)
        getter.emu_start(function, 0x200000, count=200)
        assert getter.reg_read(UC_ARM64_REG_PC) == 0x200000
        rate = getter.reg_read(UC_ARM64_REG_X0) & 0xFFFFFFFF
        assert rate == result["stock_getter_rounded_khz"]
        stock_cases.append(dict(domain=domain, stock_khz=rate, nominal_khz=result["nominal_khz"]))

    log = (args.capture / "xnu-log.bin").read_bytes()
    samples = {}
    for p, address, error, value in re.findall(
            rb"MT6762_PWRAP_SAMPLE pass=([01]) address=([0-9a-f]+) error=(-?[0-9]+) value=([0-9a-f]+)", log):
        samples.setdefault((int(address, 16), int(p)), set()).add((int(error), int(value, 16)))
    rail_words = {}
    for address in (0x14A2, 0x14A4, 0x19CC, 0x19CE):
        first, second = samples.get((address, 0)), samples.get((address, 1))
        assert first == second and first is not None and len(first) == 1
        error, value = next(iter(first))
        assert error == 0
        rail_words[address] = value
    assert rail_words[0x14A4] & 3 == 3 and rail_words[0x19CE] & 3 == 3
    rails = {}
    for name, address, shift, gray_shift in (("vproc", 0x14A2, 0, 8), ("vsram_proc", 0x19CC, 8, 0)):
        selector = (rail_words[address] >> shift) & 127
        gray = (rail_words[address] >> gray_shift) & 127
        rails[name] = dict(selector=selector, programmed_uv=518750 + 6250 * selector,
                           gray_code_consistent=gray == selector ^ (selector >> 1),
                           electrical_measurement=False)

    here = Path(__file__).resolve().parent
    source_files = [
        "vendor/mediatek/proprietary/bootable/bootloader/preloader/platform/mt6765/src/drivers/pll.c",
        "kernel-4.14/drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6765/mtk_cpufreq_platform.c",
    ]
    evidence = dict(
        method="Original bounded instructions with synthetic MMIO storage; captured raw fields independently cross-checked against the retained 4096-byte record; no phone access",
        image_sha256=sha(image), preloader_sha256=sha(preloader),
        capture_json_sha256=sha(json_blob), peripheral_record_sha256=sha(raw),
        bound_image_identity=raw[16:48].hex(), xnu_log_sha256=sha(log),
        native_header_sha256=sha((here.parents[3] / "bsd/dev/mt6762_cpufreq_protocol.h").read_bytes()),
        decoder_sha256=sha((here / "decode_clock_snapshot.py").read_bytes()),
        audit_script_sha256=sha(Path(__file__).read_bytes()),
        bsp_sources=[dict(path=path, sha256=sha((args.bsp / path).read_bytes())) for path in source_files],
        preloader=dict(start=hex(pl_start), end_exclusive=hex(pl_end),
                       code_sha256=sha(preloader[pl_start - pl_base:pl_end - pl_base]),
                       initial_r2=1, pll_control_literals=boot_literals, cases=preloader_cases),
        stock_getter=dict(start=hex(function), end_exclusive=hex(function_end),
                          code_sha256=sha(image[function - image_base:function_end - image_base]),
                          hook="_mcount only", cases=stock_cases),
        pmic_raw={hex(address): hex(value) for address, value in rail_words.items()}, rails=rails,
        ownership_granted=False, dvfs_control_ready=False,
        limitations=["Code0 unity is corroborated stock-software interpretation and inherited boot configuration, not an independent electrical frequency measurement.",
                     "Preloader replay proves mux-only writes; it does not simulate divider hardware or recover a complete hardware encoding table.",
                     "Programmed rails and inherited PLLs do not establish calibrated OPP safety or SSPM ownership."])
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    text = []
    for start, end in ((0x2244D2, 0x2244EC), (pl_start, pl_end)):
        text.extend(f"{ins.address:#010x}: {ins.mnemonic} {ins.op_str}" for ins in
                    md.disasm(preloader[start - pl_base:end - pl_base], start))
    (args.output / "inherited-clkdiv-disassembly.txt").write_text("\n".join(text) + "\n")
    (args.output / "inherited-clkdiv0.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (args.output / "capture26-clock-readback.json").write_text(json.dumps(configured, indent=2) + "\n")
    print(json.dumps(dict(stock_cases=stock_cases, rails=rails, preloader_cases=len(preloader_cases)), indent=2))


if __name__ == "__main__":
    main()
