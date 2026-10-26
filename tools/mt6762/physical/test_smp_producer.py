"""Physical multicore requests require a reviewed kernel and supported topology size."""
import hashlib,subprocess,sys,unittest
import build_payload as b

class SMPProducerTests(unittest.TestCase):
    def test_single_core_preserves_old_kernels(self):
        b.require_smp_kernel(b'olderkernel',1)

    def test_new_cpu_counts_need_reviewed_kernel(self):
        blob=b'reviewed-test-kernel';old=b.SMP_KERNELS
        try:
            b.SMP_KERNELS={hashlib.sha256(blob).hexdigest()}
            for n in (2,4,8):
                b.require_smp_kernel(blob,n)
                with self.assertRaises(ValueError):b.require_smp_kernel(blob+b'changed',n)
        finally:b.SMP_KERNELS=old

    def test_bad_cpu_counts_and_types(self):
        for n in (0,3,5,7,9,True,'2',None):
            with self.subTest(n=n),self.assertRaises(ValueError):b.require_smp_kernel(b'',n)

    def test_unsupported_count_rejected_before_io(self):
        r=subprocess.run([sys.executable,b.__file__,'--kernel','/missing','--template','/missing',
                          '--llvm','/missing','--out','/missing','--diagnostic','/missing','--cpus','3'],capture_output=True)
        self.assertEqual(r.returncode,2);self.assertIn(b'invalid choice',r.stderr);self.assertNotIn(b'FileNotFoundError',r.stderr)

if __name__=='__main__':unittest.main()
