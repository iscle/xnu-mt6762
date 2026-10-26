#!/usr/bin/env python3
"""Retained-acquisition regressions for the physical CKDIV0 observation."""
import copy
import unittest

from decode_clock_snapshot import DOMAINS, decode_snapshot


def capture_fixture():
    capture = {"state": 2, "pass_number": 2, "registers": []}
    # Independent literal capture26 vectors, rather than calculated PCWs.
    words = ((0x191, 0x811CD89D, 0x80000001, 0x10A00),
             (0x191, 0x0111B13B, 0x80000001, 0x00AFF),
             (0x191, 0x821713B1, 0x80000001, 0x10A00))
    for addresses, values in zip(DOMAINS.values(), words):
        for address, value in zip(addresses, values):
            capture["registers"].append(dict(address=hex(address), width=4, valid=3,
                                             first=value, second=value, stable=True))
    return capture


class PhysicalClockTests(unittest.TestCase):
    def test_captured_code0_rates(self):
        result = decode_snapshot(capture_fixture())
        self.assertEqual([d["nominal_khz"] for d in result["domains"].values()],
                         [1499999, 919999, 599999])
        self.assertEqual([d["stock_getter_rounded_khz"] for d in result["domains"].values()],
                         [1499500, 919500, 599750])
        self.assertFalse(result["ownership_granted"])
        self.assertFalse(result["dvfs_control_ready"])

    def test_incomplete_or_changed_samples_remain_unknown(self):
        for field, value in (("width", 2), ("valid", 1), ("stable", False),
                             ("second", 0), ("first", -1), ("first", True)):
            with self.subTest(field=field, value=value):
                capture = capture_fixture()
                capture["registers"][3][field] = value
                result = decode_snapshot(capture)["domains"]
                self.assertFalse(result["cpu0_3"]["valid"])
                self.assertIsNone(result["cpu0_3"]["nominal_khz"])
                self.assertTrue(result["cpu4_7"]["valid"])

    def test_duplicate_or_missing_register_remains_unknown(self):
        for duplicate in (False, True):
            capture = capture_fixture()
            if duplicate:
                capture["registers"].append(copy.copy(capture["registers"][3]))
            else:
                capture["registers"].pop(3)
            self.assertFalse(decode_snapshot(capture)["domains"]["cpu0_3"]["valid"])

    def test_incomplete_capture_does_not_grant_validity(self):
        for field, value in (("state", 1), ("pass_number", 1)):
            capture = capture_fixture()
            capture[field] = value
            self.assertTrue(all(not d["valid"] for d in decode_snapshot(capture)["domains"].values()))


if __name__ == "__main__":
    unittest.main()
