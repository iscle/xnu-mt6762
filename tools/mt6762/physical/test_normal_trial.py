"""Independent unsigned boot descriptor checks; no device interface."""
import hashlib
import os
from pathlib import Path
import struct
import unittest

import bootimg
from build_normal_trial import PARTITION_SIZE, validate_unsigned_boot
from test_bootimg import fixture


def avb_fixture():
    packed = bootimg.pack(fixture(), b'kernel', b'ramdisk')
    salt = hashlib.sha256(packed).digest()
    digest = hashlib.sha256(salt + packed).digest()
    desc = struct.pack('>3Q32s4I60s', 2, 184, len(packed), b'sha256', 4, 32, 32, 0, bytes(60))
    desc += b'boot' + salt + digest
    header = bytearray(256)
    header[:4] = b'AVB0'
    struct.pack_into('>IIQQI', header, 4, 1, 0, 0, 256, 0)
    struct.pack_into('>4Q', header, 64, 200, 0, 200, 0)  # Zero-size keys at aux end.
    struct.pack_into('>2Q', header, 96, 0, 200)
    offset = (len(packed) + 4095) & ~4095
    result = bytearray(PARTITION_SIZE)
    result[:len(packed)] = packed
    result[offset:offset + 256] = header
    result[offset + 256:offset + 456] = desc
    struct.pack_into('>4sIIQQQ', result, len(result) - 64, b'AVBf', 1, 0, len(packed), offset, 512)
    return bytes(result), packed, offset


class NormalBootAVBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.complete, cls.packed, cls.offset = avb_fixture()

    def test_zero_size_keys_with_bounded_nonzero_offsets(self):
        info = validate_unsigned_boot(self.complete, self.packed)
        self.assertEqual(info['partition_name'], 'boot')
        self.assertFalse(info['signature_created'])

    def test_wrong_partition_and_digest(self):
        for offset in (self.offset + 256 + 132, self.offset + 256 + 168):
            data = bytearray(self.complete); data[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                validate_unsigned_boot(data, self.packed)

    def test_metadata_bounds_flags_and_auth(self):
        for offset, fmt, value in [(12, '>Q', 64), (28, '>I', 1), (72, '>Q', 32),
                                   (64, '>Q', 257), (96, '>Q', 1), (104, '>Q', 1000),
                                   (120, '>I', 3), (256 + 16, '>Q', len(self.packed) - 1),
                                   (256 + 56, '>I', 8), (256 + 68, '>I', 1)]:
            data = bytearray(self.complete); struct.pack_into(fmt, data, self.offset + offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                validate_unsigned_boot(data, self.packed)

    def test_payload_extent_and_truncation(self):
        for complete, packed in [(self.complete[:-1], self.packed),
                                 (self.complete, self.packed + bytes(2048)),
                                 (self.complete, self.packed[:-1])]:
            with self.assertRaises(ValueError):
                validate_unsigned_boot(complete, packed)

    def test_payload_changes_rejected_even_with_valid_android_image_id(self):
        changed = bootimg.pack(fixture(), b'Kernel', b'ramdisk')
        complete = bytearray(self.complete); complete[:len(changed)] = changed
        with self.assertRaises(ValueError):
            validate_unsigned_boot(complete, changed)

    @unittest.skipUnless(os.environ.get('MTK_NORMAL_IMAGE') and os.environ.get('MTK_DIAGNOSTIC_IMAGE'),
                         'Set image paths for actual pinned producer-output validation')
    def test_actual_avbtool_output(self):
        complete = Path(os.environ['MTK_NORMAL_IMAGE']).read_bytes()
        packed = Path(os.environ['MTK_DIAGNOSTIC_IMAGE']).read_bytes()
        info = validate_unsigned_boot(complete, packed)
        self.assertEqual(info['image_size'], len(packed))


if __name__ == '__main__':
    unittest.main()
