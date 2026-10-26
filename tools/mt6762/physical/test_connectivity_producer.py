"""Exercise survey packaging/dependency failures without device access."""
from pathlib import Path
import struct
import subprocess
import sys
import unittest
import build_payload as build


class ConnectivityProducerTests(unittest.TestCase):
    def test_fixed_retained_record_is_inactive(self):
        identity=bytes(range(32))
        raw=build.connectivity_record.initialize(identity)
        report=build.connectivity_record.decode(raw,identity)
        self.assertEqual(len(raw),4096)
        self.assertEqual(build.CONNECTIVITY_ADDRESS,0x40085400)
        self.assertLessEqual(build.CONNECTIVITY_ADDRESS+len(raw),0x40090000)
        self.assertEqual(report['state_name'],'not-started')
        self.assertFalse(report['ownership_granted'])
        self.assertEqual(len(report['registers']),40)
        self.assertEqual(struct.unpack_from('<I',raw,112+21*24)[0],8)

    def test_missing_wrapper_contract_rejected_before_files(self):
        base=[sys.executable,str(Path(build.__file__)),'--kernel','/absent/kernel',
              '--template','/absent/template','--llvm','/absent/llvm',
              '--out','/absent/output','--diagnostic','/absent/pid1','--probe-connectivity']
        for extra,reason in (([],b'connectivity survey requires'),
             (['--probe-peripherals'],b'connectivity survey requires'),
             (['--native-pwrap-probe'],b'requires native display and passive')):
            result=subprocess.run(base+extra,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,2)
            self.assertIn(reason,result.stderr)
            self.assertNotIn(b'FileNotFoundError',result.stderr)


if __name__=='__main__':
    unittest.main()
