#!/usr/bin/env python3
"""Decode CPU/CCI configured rates from retained peripheral-result JSON only.

No device access, MMIO writes, firmware commands, or readiness grants. A
matching pair of samples is not an atomic snapshot or a frequency measurement.
See PHYSICAL-CLOCKS.rst for exact stock/BSP provenance and missing handoff proof.
"""

import argparse
import hashlib
import json
from pathlib import Path


DOMAINS = {
    "cpu0_3": (0x1000C21C, 0x1000C220, 0x1000C228, 0x102007A0),
    "cpu4_7": (0x1000C20C, 0x1000C210, 0x1000C218, 0x102007A4),
    "cci": (0x1000C22C, 0x1000C230, 0x1000C238, 0x102007C0),
}
FIELDS = ("con0", "con1", "power", "ckdiv")


def u32(value):
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


def decode_rate(con0, con1, power, ckdiv):
    """Same admission/arithmetic as mt6762_pll_khz; unknown never means zero."""
    if not all(u32(word) for word in (con0, con1, power, ckdiv)):
        return {"valid": False, "nominal_khz": None, "reasons": ["invalid u32"]}
    post = (con1 >> 24) & 7
    div = (ckdiv >> 17) & 31
    pcw = con1 & 0x3FFFFF
    mux = (ckdiv >> 9) & 3
    reasons = []
    if not con0 & 1:
        reasons.append("PLL disabled")
    if power & 3 != 1:
        reasons.append("PLL not powered without isolation")
    if mux != 1:
        reasons.append("source mux does not select this PLL")
    if not pcw:
        reasons.append("zero PCW")
    if post > 4:
        reasons.append("reserved postdivider")
    if 8 <= div <= 11:
        numerator, denominator = 12 - div, 4
    elif 16 <= div <= 20:
        numerator, denominator = 21 - div, 5
    elif 24 <= div <= 29:
        numerator, denominator = 30 - div, 6
    else:
        numerator, denominator = None, None
        reasons.append("unsupported/reserved CKDIV")
    rate = stock_rate = None
    if not reasons:
        rate = pcw * 26000 * numerator // (16384 * (1 << post) * denominator)
        # The exact stock getter truncates to integer MHz before dividing.
        stock_rate = (((pcw * 26) >> 14) * 1000 // (1 << post)) * numerator // denominator
        if not 0 < rate <= 0xFFFFFFFF:
            rate = stock_rate = None
            reasons.append("rate outside nonzero u32")
    return {
        "valid": not reasons,
        "nominal_khz": rate,
        "stock_getter_rounded_khz": stock_rate,
        "reasons": reasons,
        "fields": {"pcw": pcw, "postdivider_code": post, "ckdiv_code": div,
                   "source_mux": mux, "ratio_numerator": numerator,
                   "ratio_denominator": denominator},
    }


def decode_snapshot(capture):
    if not isinstance(capture, dict) or not isinstance(capture.get("registers"), list):
        raise ValueError("expected peripheral-result JSON object with register list")
    capture_reasons = []
    if type(capture.get("state")) is not int or capture["state"] != 2:
        capture_reasons.append("capture not complete")
    if type(capture.get("pass_number")) is not int or capture["pass_number"] != 2:
        capture_reasons.append("capture does not contain two passes")
    entries = {}
    for record in capture["registers"]:
        if not isinstance(record, dict):
            raise ValueError("invalid register record")
        address = record.get("address")
        try:
            address = int(address, 0) if isinstance(address, str) else address
        except ValueError as error:
            raise ValueError("invalid register address") from error
        if not u32(address):
            raise ValueError("invalid register address")
        entries.setdefault(address, []).append(record)
    domains = {}
    for domain, addresses in DOMAINS.items():
        reasons = list(capture_reasons)
        raw, registers = {}, {}
        for name, address in zip(FIELDS, addresses):
            matches = entries.get(address, [])
            registers[name] = {"address": f"0x{address:08x}", "value": None}
            if not matches:
                reasons.append(f"{name}: not captured")
                continue
            if len(matches) != 1:
                reasons.append(f"{name}: duplicate address")
                continue
            item = matches[0]
            if (type(item.get("width")) is not int or item["width"] != 4 or
                    type(item.get("valid")) is not int or item["valid"] != 3 or
                    item.get("stable") is not True or
                    not u32(item.get("first")) or not u32(item.get("second")) or
                    item["first"] != item["second"]):
                reasons.append(f"{name}: incomplete/unstable/non-u32 double read")
                continue
            raw[name] = item["first"]
            registers[name]["value"] = f"0x{item['first']:08x}"
        decoded = {"valid": False, "nominal_khz": None,
                   "stock_getter_rounded_khz": None, "reasons": reasons}
        if not reasons:
            decoded = decode_rate(**raw)
        domains[domain] = dict(decoded, registers=registers)
    return {
        "schema": "mt6762-configured-cpu-clocks-v1",
        "reference_khz": 26000,
        "domains": domains,
        "ownership_granted": False,
        "dvfs_control_ready": False,
        "device_access_performed": False,
        "limitations": [
            "Configured nominal rates; no hardware frequency-counter measurement.",
            "Two equal read passes do not prove atomicity or exclude an intervening change.",
            "This parser does not authenticate capture acquisition or verify the claimed peripheral-record digest.",
            "No PMIC electrical measurement, calibrated OPP, SSPM liveness, or thermal/current budget proof.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    blob = args.capture.read_bytes()
    try:
        capture = json.loads(blob)
        report = decode_snapshot(capture)
    except (ValueError, TypeError) as error:
        parser.error(str(error))
    report["input"] = {"path": str(args.capture.resolve()),
                       "file_sha256": hashlib.sha256(blob).hexdigest(),
                       "claimed_peripheral_record_sha256": capture.get("sha256")}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
