#!/usr/bin/env python3
"""Exercise actual physical ADT identity publication, never a device."""
import unittest
from build_payload import decode_adt, encode_adt, physical_identity


class FactoryIdentityTests(unittest.TestCase):
    def props(self):
        return {'unique-chip-id': b'lab-chip', 'mac-address-wifi0': b'lab-wifi',
                'mac-address-bluetooth0': b'lab-bt', 'unrelated': b'preserve'}

    def test_absent_input_drops_lab_identities(self):
        props = self.props()
        physical_identity(props)
        self.assertEqual(props, {'unrelated': b'preserve'})

    def test_raw_bytes_survive_real_adt_roundtrip(self):
        # Explicit synthetic fixture, not a production/default identity.
        for value in (bytes.fromhex('001122334455'), bytes.fromhex('021122334455')):
            props = self.props()
            physical_identity(props, value)
            tree = {'name': 'chosen', 'props': props, 'children': []}
            blob = encode_adt(tree)
            decoded, end, _ = decode_adt(blob)
            self.assertEqual(end, len(blob))
            self.assertEqual(decoded['props'], {'unrelated': b'preserve',
                                               'mac-address-wifi0': value})

    def test_bad_identity_rejected_without_mutating_tree(self):
        bad = [bytes(n) for n in (0, 1, 5, 6, 7, 17)]
        bad += [b'00:11:22:33:44:55', bytes.fromhex('ffffffffffff'),
                bytes.fromhex('011122334455')]
        for value in bad:
            with self.subTest(value=value):
                props = self.props()
                with self.assertRaises(ValueError):
                    physical_identity(props, value)
                self.assertEqual(props, self.props())


if __name__ == '__main__':
    unittest.main()
