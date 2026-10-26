"""Failure ordering for the bounded physical storage writer; no phone access."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from desktop_ramdisk import USERDATA_START
from install_system_slice import install


class SliceInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'system.apfs'
        self.content = bytes(range(256))*6
        self.source.write_bytes(self.content)
        self.backup = self.root/'before.bin'
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.medium = bytearray(b'x'*len(self.content))
        self.original = bytes(self.medium)
        self.events = []
        self.writes = []
        self.guards = 0
        self.bad_write = False
        self.bad_read = False
        self.short_read = False
        self.fail_guard = None
        self.mutate_source = False

    def guard(self):
        self.guards += 1
        if self.guards == self.fail_guard:
            raise RuntimeError('fresh partition guard failed')
        if self.guards == 2 and self.mutate_source:
            self.source.write_bytes(b'y'*len(self.content))

    def read(self, address, size):
        offset = address-USERDATA_START*512
        self.assertTrue(0 <= offset < len(self.medium))
        self.assertLessEqual(offset+size,len(self.medium))
        data = bytes(self.medium[offset:offset+size])
        if self.short_read:
            return data[:-1]
        if self.bad_read and self.writes:
            return bytes([data[0]^1])+data[1:]
        return data

    def write(self, address, data):
        offset = address-USERDATA_START*512
        self.assertTrue(0 <= offset < len(self.medium))
        self.assertLessEqual(offset+len(data),len(self.medium))
        self.writes.append((address,len(data)))
        if self.bad_write:
            return False
        self.medium[offset:offset+len(data)] = data
        return True

    def run_install(self, **overrides):
        args = dict(io=self,source=self.source,backup=self.backup,
                    expected_sha256=self.digest,start=USERDATA_START,count=3,
                    guard=self.guard,record=self.events.append,chunk_bytes=1024)
        args.update(overrides)
        return install(**args)

    def test_complete_backup_precedes_writes_and_all_bytes_verified(self):
        result = self.run_install()
        self.assertEqual(self.backup.read_bytes(),self.original)
        self.assertEqual(self.medium,self.content)
        self.assertEqual([size for _,size in self.writes],[1024,512])
        self.assertEqual(self.events[0]['stage'],'backup_complete')
        self.assertEqual(result['full_readback_sha256'],self.digest)
        self.assertFalse(result['reset_requested'])
        self.assertEqual(self.guards,3)

    def test_bad_source_never_touches_media(self):
        with self.assertRaises(RuntimeError):
            self.run_install(expected_sha256='0'*64)
        self.assertEqual(self.guards,0)
        self.assertEqual(self.writes,[])
        self.assertFalse(self.backup.exists())

    def test_bad_bounds_never_touch_media(self):
        with self.assertRaises(ValueError):
            self.run_install(start=USERDATA_START-1)
        self.assertEqual(self.guards,0)
        self.assertEqual(self.writes,[])

    def test_backup_failure_and_changed_source_stop_before_write(self):
        self.short_read = True
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertEqual(self.writes,[])
        self.backup.unlink()
        self.short_read = False
        self.mutate_source = True
        self.guards = 0
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertEqual(self.writes,[])
        self.assertEqual(self.backup.read_bytes(),self.original)

    def test_prewrite_guard_and_existing_backup_refuse(self):
        self.fail_guard = 2
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertEqual(self.writes,[])
        self.fail_guard = None
        with self.assertRaises(FileExistsError):
            self.run_install()
        self.assertEqual(self.writes,[])

    def test_uncertain_write_and_readback_error_never_retry(self):
        self.bad_write = True
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertEqual(len(self.writes),1)
        self.backup.unlink()
        self.writes.clear()
        self.bad_write = False
        self.bad_read = True
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertEqual(len(self.writes),1)
        self.assertEqual(self.events[-1]['stage'],'write_begin')

    def test_postwrite_guard_does_not_report_completion(self):
        self.fail_guard = 3
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertEqual(self.medium,self.content)
        self.assertNotIn('complete',[e['stage'] for e in self.events])


if __name__ == '__main__':
    unittest.main()
