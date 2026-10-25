import struct
import unittest
import trace_record as trace


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.identity = bytes(range(32))

    def test_initialized_is_not_execution(self):
        info = trace.decode(trace.initialized(self.identity), self.identity)
        self.assertFalse(info['executed'])
        self.assertFalse(info['proves_xnu_executed'])

    def test_build_identity_refuses_stale(self):
        with self.assertRaisesRegex(ValueError, 'stale'):
            trace.decode(trace.initialized(self.identity), bytes(reversed(self.identity)))

    def test_phase_does_not_prove_xnu_or_retention(self):
        raw = bytearray(trace.initialized(self.identity))
        struct.pack_into('<4Q', raw, 48, 10, trace.MASK ^ 10, 11, trace.MASK ^ 11)
        struct.pack_into('<Q', raw, 80, 9)
        value = trace.decode(raw, self.identity)
        self.assertTrue(value['executed'])
        self.assertFalse(value['proves_xnu_executed'])
        self.assertFalse(value['physical_ram_retention_proven'])

    def test_malformed_and_torn(self):
        original = trace.initialized(self.identity)
        for offset in (0, 8, 12, 48, 56, 64, 72, 80, 208, 255):
            raw = bytearray(original); raw[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                trace.decode(raw, self.identity)
        for size in (0, 16, 48, 255, 257):
            with self.subTest(size=size), self.assertRaises(ValueError):
                trace.decode((original + b'x')[:size], self.identity)

    def test_refusal_retains_detail(self):
        raw = bytearray(trace.initialized(self.identity))
        struct.pack_into('<4Q', raw, 48, 254, trace.MASK ^ 254, 8, trace.MASK ^ 8)
        struct.pack_into('<2Q', raw, 80, 6, 0x208)
        value = trace.decode(raw, self.identity)
        self.assertEqual(value['detail'], 0x208)
        self.assertEqual(value['previous_phase'], 6)


if __name__ == '__main__':
    unittest.main()
