"""Synthetic storage fault tests; no claim of physical DA behavior."""
import hashlib
import unittest
from unittest.mock import patch
import recovery_bcb as bcb


class Storage:
    def __init__(self, para):
        self.para = para
        self.recovery = bytes(bcb.RECOVERY_SIZE)
        self.events = []
        self.write_ok = True
        self.corrupt_write = False

    def read(self, address, size):
        self.events.append(('read', address, size))
        if address == bcb.RECOVERY_ADDRESS and size == bcb.RECOVERY_SIZE:
            return self.recovery
        if address == bcb.PARA_ADDRESS and size == bcb.PARA_SIZE:
            return self.para
        raise AssertionError('Unexpected storage extent')

    def write(self, address, data):
        self.events.append(('write', address, len(data)))
        assert address == bcb.PARA_ADDRESS and len(data) == 512
        if not self.write_ok:
            return False
        self.para = data + self.para[512:]
        if self.corrupt_write:
            self.para = self.para[:1000] + bytes([self.para[1000] ^ 1]) + self.para[1001:]
        return True


class CommandTests(unittest.TestCase):
    def setUp(self):
        data = bytearray(b'\xa5' * bcb.PARA_SIZE)
        data[0] = data[64] = 0
        self.before = bytes(data)
        self.io = Storage(self.before)
        # Explicitly synthetic recovery content, never passed as real evidence.
        self.pin = patch.object(bcb, 'CANDIDATE_SHA256', hashlib.sha256(self.io.recovery).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def test_arm_checks_recovery_then_backup_and_preserves_other_bytes(self):
        result = bcb.arm(self.io, self.before)
        self.assertEqual(self.io.para[:32], bcb.COMMAND)
        self.assertEqual(self.io.para[32:], self.before[32:])
        self.assertEqual(self.io.events, [
            ('read', bcb.RECOVERY_ADDRESS, bcb.RECOVERY_SIZE),
            ('read', bcb.PARA_ADDRESS, bcb.PARA_SIZE),
            ('write', bcb.PARA_ADDRESS, 512),
            ('read', bcb.PARA_ADDRESS, bcb.PARA_SIZE)])
        self.assertTrue(result['full_readback_verified'])

    def test_wrong_recovery_or_changed_backup_never_writes(self):
        for address in ('recovery', 'para'):
            with self.subTest(address=address):
                io = Storage(self.before)
                original = getattr(io, address)
                setattr(io, address, original[:-1] + bytes([original[-1] ^ 1]))
                with self.assertRaises(ValueError):
                    bcb.arm(io, self.before)
                self.assertFalse(any(e[0] == 'write' for e in io.events))

    def test_pending_command_and_recovery_arguments_rejected(self):
        for offset in (0, 64):
            data = bytearray(self.before)
            data[offset] = ord('r')
            with self.assertRaises(ValueError):
                bcb.arm(self.io, bytes(data))
        self.assertEqual(self.io.events, [])

    def test_write_failure_and_unrelated_readback_corruption_stop(self):
        for fault in ('write_ok', 'corrupt_write'):
            io = Storage(self.before)
            setattr(io, fault, fault == 'corrupt_write')
            with self.assertRaises(IOError):
                bcb.arm(io, self.before)
            self.assertEqual(sum(e[0] == 'write' for e in io.events), 1)

    def test_restore_keeps_new_status_and_tail(self):
        current = bytearray(bcb.arm_image(self.before))
        current[32:40] = b'newstate'
        current[-1] ^= 1
        self.io.para = bytes(current)
        bcb.restore(self.io, self.before)
        self.assertEqual(self.io.para[:32], self.before[:32])
        self.assertEqual(self.io.para[32:], current[32:])

    def test_foreign_marker_is_not_overwritten(self):
        self.io.para = b'boot-fastboot'.ljust(32, b'\0') + self.before[32:]
        with self.assertRaises(ValueError):
            bcb.restore(self.io, self.before)
        self.assertFalse(any(e[0] == 'write' for e in self.io.events))

    def test_already_restored_is_checked_without_write(self):
        result = bcb.restore(self.io, self.before)
        self.assertEqual(result['written_bytes'], 0)
        self.assertFalse(any(e[0] == 'write' for e in self.io.events))

    def test_truncated_baseline_has_no_io(self):
        with self.assertRaises(ValueError):
            bcb.arm(self.io, self.before[:-1])
        self.assertEqual(self.io.events, [])

    def test_reviewed_unsupported_bootloader_marker_requires_explicit_option(self):
        baseline = bcb.BOOTLOADER_REQUEST + self.before[32:]
        io = Storage(baseline)
        with self.assertRaises(ValueError):
            bcb.arm(io, baseline)
        self.assertEqual(io.events, [])
        bcb.arm(io, baseline, allow_bootloader_request=True)
        self.assertEqual(io.para[:32], bcb.COMMAND)
        bcb.restore(io, baseline, allow_bootloader_request=True)
        self.assertEqual(io.para, baseline)
        arguments = bytearray(baseline)
        argument_text = b'recovery\n--wipe_data'
        arguments[64:64+len(argument_text)] = argument_text
        for bad in (b'boot-fastboot'.ljust(32, b'\0') + self.before[32:], bytes(arguments)):
            self.assertEqual(len(bad), bcb.PARA_SIZE)
            with self.assertRaises(ValueError):
                bcb.arm_image(bad, allow_bootloader_request=True)


if __name__ == '__main__':
    unittest.main()
