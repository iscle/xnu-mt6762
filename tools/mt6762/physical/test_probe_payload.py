#!/usr/bin/env python3
"""Fixture/RSP framing tests; emulator execution is a separate integration test."""
import socket
import struct
import threading
import unittest

from probe_payload import runtime_fdt, display_fdt, RSP
from test_fdt_handoff import fdt, node, U32, U64


class FixtureTests(unittest.TestCase):
    def test_only_existing_memory_size_changes(self):
        original = fdt(node('', [('#address-cells', U32(2)), ('#size-cells', U32(2))], [
            node('memory@40000000', [('reg', U64(0x40000000) + U64(0x20000000))]),
            node('reserved-memory', [('alloc-ranges', U64(0x40000000) + U64(0x90000000))])]),
            [(0xc0000000, 0x10000000)])
        modified, offset = runtime_fdt(original, 0x100000000)
        self.assertEqual(len(modified), len(original))
        self.assertEqual(modified[:offset], original[:offset])
        self.assertEqual(modified[offset+8:], original[offset+8:])
        self.assertEqual(struct.unpack_from('>Q', modified, offset)[0], 0x100000000)

    def test_ambiguous_memory_rejected(self):
        memory = node('memory@40000000', [('reg', U64(0x40000000) + U64(0x20000000))])
        with self.assertRaises(ValueError):
            runtime_fdt(fdt(node('', [], [memory, memory])), 0x100000000)

    def test_display_tag_layout_and_explicit_reservation(self):
        original = fdt(node('', [], [node('chosen', [('bootargs', b'preserved\0')])]),
                       [(0x50000000, 0x1000)])
        modified = display_fdt(original)
        h = struct.unpack_from('>10I', modified)
        self.assertEqual(h[1], len(modified))
        self.assertEqual(struct.unpack_from('>QQ', modified, h[4]), (0x50000000, 0x1000))
        self.assertEqual(struct.unpack_from('>QQ', modified, h[4] + 16), (0x7ef90000, 0x470000))
        self.assertIn(b'preserved\0', modified)
        marker = modified.index(struct.pack('<QIII', 0x7ef90000, 1, 6000, 0x470000))
        length, = struct.unpack_from('>I', modified, marker - 8)
        self.assertEqual(length % 4, 0)
        with self.assertRaises(ValueError):
            display_fdt(modified)

    def test_rsp_escaping_and_fragmented_checksum(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close); self.addCleanup(right.close)
        rsp = RSP.__new__(RSP); rsp.sock = left
        encoded = b'lA}\x03B'  # Escaped '#' in transferred XML data.
        packet = b'+$' + encoded + b'#' + f'{sum(encoded)&255:02x}'.encode()
        def sender():
            for byte in packet:
                right.sendall(bytes([byte]))
            self.assertEqual(right.recv(1), b'+')
        thread = threading.Thread(target=sender)
        thread.start()
        self.assertEqual(rsp.receive(), 'lA#B')
        thread.join()

    def test_rsp_bad_checksum_rejected(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close); self.addCleanup(right.close)
        rsp = RSP.__new__(RSP); rsp.sock = left
        right.sendall(b'$OK#00')
        with self.assertRaises(RuntimeError):
            rsp.receive()


if __name__ == '__main__':
    unittest.main()
