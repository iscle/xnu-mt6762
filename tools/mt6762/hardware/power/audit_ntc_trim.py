#!/usr/bin/env python3
"""Offline exact-artifact evidence; never admits calibrated temperature.

No device access. Register decoding describes supplied header bitfields only;
it deliberately does not invent the hardware selector-to-coefficient mapping.
"""
import argparse
import hashlib
import json
import struct
from fractions import Fraction
from pathlib import Path

IMAGE_SHA256 = "82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b"
BASE = 0xFFFFFF8008080000
CHANNELS = 0xFFFFFF80098932C8
REGS = 0xFFFFFF8009105EF8


def decode_trim(words):
    """Decode a caller-supplied snapshot, without treating it as live evidence."""
    needed = (0x1008, 0x10DE, 0x10E0, 0x113A, 0x113C,
              0x11A2, 0x11A4, 0x11A6, 0x11A8, 0x11AA, 0x11AC)
    missing = [hex(a) for a in needed if a not in words]
    if missing:
        return dict(complete=False, missing=missing, calibrated=False)
    if any(type(words[a]) is not int or not 0 <= words[a] <= 0xFFFF for a in needed):
        raise ValueError("snapshot words must be unsigned 16-bit integers")
    return dict(
        complete=True, calibrated=False,
        ch3_selector=(words[0x113A] >> 6) & 3,
        ch11_selector=(words[0x113C] >> 6) & 3,
        adc_2s_comp_enb=(words[0x113C] >> 14) & 1,
        adc_trim_comp=(words[0x113C] >> 15) & 1,
        analog_cali=words[0x1008] & 15,
        sw_gain_raw=words[0x10DE] & 0x7FFF,
        sw_offset_raw=words[0x10E0] & 0x7FFF,
        efuse_raw={f"ch{ch}": dict(gain=words[a] & 0xFFF,
                                    offset=words[a + 2] & 0x7FF)
                   for ch, a in [(4, 0x11A2), (0, 0x11A6), (7, 0x11AA)]},
        missing_semantics=["selector coefficient-bank mapping", "gain units",
                           "offset encoding/units", "compensation enable semantics",
                           "factory-shadow validity and physical calibration"],
    )


def ratio_examples():
    # Synthetic exact rational arithmetic, not sensor or calibration vectors.
    def resistance(n, b, correction=0):
        return Fraction(16900) * (n - correction) / (b - n)
    n, b, g, o, correction = map(Fraction, (600, 1800, 2, 10, 5))
    nominal = resistance(n, b)
    rows = {
        "nominal": nominal,
        "same_gain_zero_offset": resistance(g * n, g * b),
        "same_gain_common_offset": resistance(g * n + o, g * b + o),
        "different_gains": resistance(g * n, b),
        "physical_correction_nominal": resistance(n, b, correction),
        "physical_correction_wrong_unscaled_gain": resistance(g * n, g * b, correction),
        "physical_correction_gain_scaled": resistance(g * n, g * b, g * correction),
        "raw_1400_4089": resistance(1400, 4089),
        "stock_separate_mv_floor_1400_4089": resistance(1400 * 1800 // 4096,
                                                       4089 * 1800 // 4096),
    }
    assert rows["same_gain_zero_offset"] == nominal
    assert rows["same_gain_common_offset"] != nominal
    assert rows["different_gains"] != nominal
    assert rows["physical_correction_wrong_unscaled_gain"] != rows["physical_correction_nominal"]
    assert rows["physical_correction_gain_scaled"] == rows["physical_correction_nominal"]
    assert rows["raw_1400_4089"] != rows["stock_separate_mv_floor_1400_4089"]
    return {name: dict(ohms_numerator=v.numerator, ohms_denominator=v.denominator)
            for name, v in rows.items()}


def audit(image, preloader):
    digest = hashlib.sha256(image).hexdigest()
    if digest != IMAGE_SHA256:
        raise ValueError("this bounded audit is specific to the supplied Image")
    pattern = struct.pack("<8H", 0x113A, 0x95D0, 0xFFF0, 0,
                          0x113C, 0x55, 0xFF, 0)
    offset = preloader.find(pattern)
    if offset != 0x38040 or preloader.find(pattern, offset + 1) != -1:
        raise ValueError("expected unique supplied-preloader table absent")
    channels = []
    for index, expected_hw, expected_output in [(3, 3, 0x108E), (14, 11, 0x109E)]:
        off = CHANNELS - BASE + index * 64
        nameptr = struct.unpack_from("<Q", image, off + 16)[0]
        name = image[nameptr - BASE:].split(b"\0", 1)[0].decode("ascii")
        hw, resolution = struct.unpack_from("BB", image, off + 24)
        # The MT6357 register table is indexed by logical channel, not hw channel.
        req, shift, output = struct.unpack_from("<III", image, REGS - BASE + index * 12)
        assert (hw, resolution, req, shift, output) == (expected_hw, 12, 0x110E, expected_hw, expected_output)
        channels.append(dict(logical_index=index, name=name, hardware_channel=hw,
                             resolution=resolution, request=hex(req), request_shift=shift,
                             output=hex(output)))
    # A complete synthetic snapshot remains inadmissible even with equal selectors.
    synthetic = dict.fromkeys((0x1008, 0x10DE, 0x10E0, 0x113A, 0x113C,
                               0x11A2, 0x11A4, 0x11A6, 0x11A8, 0x11AA, 0x11AC), 0)
    assert not decode_trim(synthetic)["calibrated"]
    assert not decode_trim({})["complete"]
    return dict(
        image_sha256=digest, preloader_sha256=hashlib.sha256(preloader).hexdigest(),
        method="bounded static records and exact rational counterexamples; no hardware or ARM64 execution",
        physical_hardware_tested=False, calibrated_temperature_admitted=False,
        channels=channels,
        preloader_records=[dict(file_offset=hex(offset + i * 8), address=hex(a),
                                value=hex(v), mask=hex(m), shift=s,
                                decoded_channel_selector=(v >> 6) & 3)
                           for i, (a, v, m, s) in enumerate([
                               (0x113A, 0x95D0, 0xFFF0, 0), (0x113C, 0x55, 0xFF, 0)])],
        preloader_caveat="embedded configuration records, not proof of current registers or selector semantics; 113c upper compensation bits are not covered by this mask",
        stock_processed_formula="((raw * resistance_ratio_numerator * 1800) / resistance_ratio_denominator) >> resolution; integer operations",
        ratio_math_synthetic=ratio_examples(),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("image", type=Path)
    p.add_argument("preloader", type=Path)
    args = p.parse_args()
    print(json.dumps(audit(args.image.read_bytes(), args.preloader.read_bytes()), indent=2))
