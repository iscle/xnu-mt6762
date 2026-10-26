"""Boundary/corruption checks for the physical desktop bootstrap inputs."""
import struct
import unittest

from desktop_ramdisk import (USERDATA_START, USERDATA_SECTORS,
                             validate_bootstrap, validate_slice)


class DesktopInputTests(unittest.TestCase):
    def image(self, blocks=1):
        data = bytearray(blocks * 4096)
        struct.pack_into('<4sIQ', data, 32, b'NXSB', 4096, blocks)
        # Fixed vectors independently generated with the existing APFS writer.
        checksums = {1: 0x3b05ea8d82a6ad23, 1024: 0x3b15be978296d51a}
        struct.pack_into('<Q', data, 0, checksums[blocks])
        return data

    def test_known_geometry_and_checksum_vectors(self):
        for count in (1, 1024):
            info = validate_bootstrap(self.image(count))
            self.assertEqual(info['block_count'], count)
            self.assertTrue(info['nxsb_checksum_verified'])
            self.assertFalse(info['filesystem_contents_verified'])

    def test_corrupt_metadata_and_extent_rejected(self):
        for offset in (0, 8, 31, 32, 36, 40, 4095):
            bad = self.image(); bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                validate_bootstrap(bad)
        for bad in (b'', self.image()[:-1], self.image()+bytes(4096), bytes(33*1024*1024)):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                validate_bootstrap(bad)

    def test_userdata_boundaries(self):
        end = USERDATA_START + USERDATA_SECTORS
        for start,count in ((USERDATA_START,1), (end-1,1),
                            (USERDATA_START,USERDATA_SECTORS), (12566528,4865552)):
            self.assertTrue(validate_slice(start,count)['read_only'])
        for start,count in ((0,1),(-1,1),(USERDATA_START-1,1),(USERDATA_START,0),
                            (USERDATA_START,-1),(end,1),(end-1,2),
                            (USERDATA_START,USERDATA_SECTORS+1),(1<<64,1),
                            (USERDATA_START,1<<64)):
            with self.subTest(start=start,count=count), self.assertRaises(ValueError):
                validate_slice(start,count)


if __name__ == '__main__':
    unittest.main()
