"""Reject physical trial requests that cannot be honored by their kernel."""
import unittest
from build_payload import trial_bootarg


class TrialArgumentTests(unittest.TestCase):
    marker = b'MT6762_TRIAL armed seconds=%u'

    def test_disabled_preserves_existing_images(self):
        self.assertEqual(trial_bootarg(b'', 0, False), '')
        self.assertEqual(trial_bootarg(self.marker, 0, True), '')

    def test_explicit_supported_deadline(self):
        for seconds in (60, 300, 1800):
            self.assertEqual(trial_bootarg(self.marker, seconds, True),
                             f' mt6762_trial_seconds={seconds}')

    def test_old_kernel_or_missing_refresh_rejected(self):
        for kernel, refresh in ((b'', True), (self.marker, False)):
            with self.assertRaises(ValueError):
                trial_bootarg(kernel, 300, refresh)

    def test_bad_boundaries_and_types_rejected(self):
        for seconds in (-1, 1, 59, 1801, 2**64, True, '300'):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                trial_bootarg(self.marker, seconds, True)


if __name__ == '__main__':
    unittest.main()
