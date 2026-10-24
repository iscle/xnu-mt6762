import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest

from planner import KEY, PARTITION_SIZE, build_candidate, inspect
from mtk_adapter import authenticated_candidate, checked_seccfg_class, prepare_from_connected_mtk


def descriptor(key, value):
    return struct.pack('>3I', 0x90790804, len(key), len(value)) + key + value


def fixture(records=None, status=1):
    data = bytearray(PARTITION_SIZE)
    struct.pack_into('<7I', data, 0, 0x4d4d4d4d, 4, 60, 3, status, 0, 0x45454545)
    data[60:512] = bytes((n * 29 + 3) % 256 for n in range(452))
    struct.pack_into('>3I', data, 512, 0x90790922, 1, 0)
    packed = b''.join(records if records is not None else [descriptor(KEY, bytes(range(32)))])
    data[0x240:0x240 + len(packed)] = packed
    # Tail sentinels must survive; they are outside the parsed record sequence.
    data[-64:] = bytes(range(64))
    return bytes(data)


class PlannerTests(unittest.TestCase):
    def test_only_three_ranges_change_and_unrelated_records_preserved(self):
        source = fixture([descriptor(b'other', b'private-value'),
                          descriptor(KEY, bytes(range(32))),
                          descriptor(KEY + b'-other', b'unrelated')])
        candidate, report = build_candidate(source, lambda header: bytes([0x5a]) * 32)
        offset = inspect(source)['managed_value_offset']
        self.assertEqual(candidate[offset:offset + 32], bytes(32))
        self.assertEqual(candidate[:16], source[:16])
        self.assertEqual(candidate[20:28], source[20:28])
        self.assertEqual(candidate[60:offset], source[60:offset])
        self.assertEqual(candidate[offset + 32:], source[offset + 32:])
        self.assertFalse(report['authenticated'])
        self.assertEqual([s['offset'] for s in report['changed_sectors']], [0, 512])

    def test_status_zero_preserves_original_auth(self):
        source = fixture(status=0)
        def forbidden(_):
            self.fail('Unchanged header must not be reencrypted')
        candidate, _ = build_candidate(source, forbidden)
        self.assertEqual(candidate[:512], source[:512])

    def test_missing_record_never_creates_one(self):
        source = fixture([])
        candidate, report = build_candidate(source, lambda _: bytes(32))
        self.assertIsNone(report['managed_value_offset'])
        self.assertEqual(candidate[512:], source[512:])

    def test_bad_sizes_and_header_states(self):
        original = fixture()
        for size in (0, 59, 512, PARTITION_SIZE - 1, PARTITION_SIZE + 1):
            with self.subTest(size=size), self.assertRaises(ValueError):
                inspect((original + b'x')[:size])
        for offset, value in ((0, 0), (4, 3), (8, 64), (12, 1), (12, 4), (16, 2), (24, 0)):
            bad = bytearray(original)
            struct.pack_into('<I', bad, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                inspect(bad)

    def test_malformed_records(self):
        for records in ([descriptor(KEY, bytes(31))],
                        [descriptor(KEY, bytes(33))],
                        [descriptor(KEY, bytes(32))] * 2,
                        [descriptor(bytes([65 + i]), b'x') for i in range(9)]):
            with self.subTest(records=len(records)), self.assertRaises(ValueError):
                inspect(fixture(records))
        for offset, value in ((0x200, 0), (0x204, 2), (0x208, 1),
                              (0x20c, 1), (0x240, 123), (0x244, 0xffffffff),
                              (0x248, 0xffffffff), (0x283 + 4, 1)):
            bad = bytearray(fixture())
            struct.pack_into('>I', bad, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect(bad)

    def test_callback_bounds(self):
        for value in (b'', bytes(31), bytes(33), None, 'x' * 32):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                build_candidate(fixture(), lambda _, value=value: value)

    def test_exact_key_not_prefix(self):
        source = fixture([descriptor(KEY + b'\0', bytes(32))])
        candidate, report = build_candidate(source, lambda _: bytes(32))
        self.assertIsNone(report['managed_value_offset'])
        self.assertEqual(candidate[512:], source[512:])


class SyntheticSej:
    """TEST DOUBLE ONLY, not a cryptographic implementation or device fixture."""
    def __init__(self):
        self.calls = []
    def sej_sec_cfg_sw(self, data, encrypt):
        return bytes(32)
    def sej_sec_cfg_hw(self, data, encrypt):
        return bytes(32)
    def sej_sec_cfg_hw_V3(self, data, encrypt, legacy=False):
        self.calls.append((encrypt, legacy))
        if not legacy:
            return bytes(32)
        return bytes(v ^ 0xa5 for v in data)


@unittest.skipUnless(os.environ.get('MTK_CAPTURE_DIR'), 'Set MTK_CAPTURE_DIR for local capture structural checks')
class LocalCaptureTests(unittest.TestCase):
    def test_before_after_captures_without_hardware_auth_claim(self):
        directory = Path(os.environ['MTK_CAPTURE_DIR'])
        before = (directory / 'seccfg-before.bin').read_bytes()
        with self.assertRaises(ValueError):
            inspect(before)  # Locked backup must never become a repair source.
        after = (directory / 'seccfg-after.bin').read_bytes()
        self.assertIsNone(inspect(after)['managed_value_offset'])
        post = (directory / 'seccfg-posttrial.bin').read_bytes()
        info = inspect(post)
        self.assertEqual(info['managed_value_offset'], 0x263)
        self.assertEqual(info['records'][0]['key_size'], 23)
        self.assertEqual(info['records'][0]['value_size'], 32)
        # Explicit dummy signature checks structural preservation only.
        candidate, report = build_candidate(post, lambda _: bytes(32))
        self.assertFalse(report['authenticated'])
        self.assertEqual(candidate[0x283:], post[0x283:])
        self.assertEqual(candidate[60:0x263], post[60:0x263])


@unittest.skipUnless(os.environ.get('MTK_CHECKOUT'), 'Set MTK_CHECKOUT for reviewed imported-parser adapter tests')
class ImportedAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.environ['MTK_CHECKOUT'])
        cls.sc, _ = checked_seccfg_class(os.environ['MTK_CHECKOUT'])

    def setUp(self):
        self.sej = SyntheticSej()
        self.hwc = types.SimpleNamespace(sej=self.sej)
        self.mtk = types.SimpleNamespace(config=types.SimpleNamespace(gui=None, hwcode=0x766))
        raw = bytearray(fixture())
        raw[28:60] = self.sej.sej_sec_cfg_hw_V3(hashlib.sha256(raw[:28]).digest(), True, legacy=True)
        self.raw = bytes(raw)

    def test_real_parser_with_explicit_test_crypto_and_legacy_branch(self):
        candidate, report = authenticated_candidate(self.raw, self.hwc, self.mtk, self.sc)
        self.assertTrue(report['authenticated'])
        self.assertEqual(report['authentication_variant'], 'V4')
        self.assertEqual(struct.unpack_from('<II', candidate, 12), (3, 0))
        self.assertEqual(self.sej.calls.count((True, True)), 2)

    def test_corrupt_existing_auth_refused(self):
        bad = bytearray(self.raw)
        bad[30] ^= 1
        with self.assertRaises(ValueError):
            authenticated_candidate(bytes(bad), self.hwc, self.mtk, self.sc)

    def test_corrupt_generated_auth_refused(self):
        original = self.sej.sej_sec_cfg_hw_V3
        self.sej.sej_sec_cfg_hw_V3 = lambda data, encrypt, legacy=False: bytes(32) if encrypt else original(data, encrypt, legacy)
        with self.assertRaises(ValueError):
            authenticated_candidate(self.raw, self.hwc, self.mtk, self.sc)

    def mock_da(self, reread=None):
        part = types.SimpleNamespace(name='seccfg', sector=0xf000000 // 512, sectors=PARTITION_SIZE // 512)
        reads = iter([self.raw, self.raw if reread is None else reread])
        def readflash(**kwargs):
            self.assertEqual(kwargs['addr'], 0xf000000)
            self.assertEqual(kwargs['length'], PARTITION_SIZE)
            return next(reads)
        # No write API exists on this test object: an accidental flash write fails.
        self.mtk.daloader = types.SimpleNamespace(
            xft=types.SimpleNamespace(cryptosetup=lambda: self.hwc),
            daconfig=types.SimpleNamespace(pagesize=512),
            get_partition_data=lambda **kwargs: [part], readflash=readflash)

    def test_local_artifacts_only(self):
        self.mock_da()
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'review'
            report = prepare_from_connected_mtk(self.mtk, out, os.environ['MTK_CHECKOUT'])
            self.assertFalse(report['flash_writes_performed'])
            self.assertEqual((out / 'seccfg-fresh.bin').read_bytes(), self.raw)
            self.assertEqual((out / 'seccfg-candidate.bin').stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(report['changed_sectors']), 2)
            with self.assertRaises(FileExistsError):
                prepare_from_connected_mtk(self.mtk, out, os.environ['MTK_CHECKOUT'])

    def test_snapshot_change_rejects_candidate(self):
        self.mock_da(reread=fixture())
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'review'
            with self.assertRaises(ValueError):
                prepare_from_connected_mtk(self.mtk, out, os.environ['MTK_CHECKOUT'])
            self.assertTrue((out / 'seccfg-fresh.bin').exists())
            self.assertFalse((out / 'seccfg-candidate.bin').exists())


if __name__ == '__main__':
    unittest.main()
