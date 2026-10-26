"""Captured keypad admission and changing-state refusal; no device writes."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
READ=C.CFUNCTYPE(C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint)


class NativeKeysTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        root=Path(cls.tmp.name)
        (root/'keys.c').write_text('#include "mt6762_keys_entry.h"\n'
            'int check(uint32_t (*r)(void *,uint32_t,unsigned)){return mt6762_keys_entry_ok(r,0);}\n')
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
            '-I'+str(HERE.parent/'hardware/power'),str(root/'keys.c'),'-o',str(root/'keys.so')],check=True)
        cls.lib=C.CDLL(str(root/'keys.so'));cls.lib.check.argtypes=[READ]

    def good(self):
        # Physical capture20; matrix values deliberately excluded from admission.
        return {0x0c000118:0,0x0c000318:0,0x100053b0:0x11110210,
                0x10010024:1,0x10010018:0x400,0x10010020:0x1c70}

    def check(self,values,change=None):
        reads=[]
        def read(ctx,address,width):
            reads.append((address,width))
            value=values[address]
            return change(address,value,len(reads)) if change else value
        return self.lib.check(READ(read)),reads

    def test_captured_state_and_mmio_widths(self):
        result,reads=self.check(self.good())
        self.assertEqual(result,1)
        self.assertEqual(len(reads),12)
        self.assertEqual(reads[:6],reads[6:])
        for a,w in reads:
            self.assertEqual(w,2 if a>=0x10010000 else 4)
        self.assertNotIn((0x10010004,2),reads) # boot-held keys must not block entry

    def test_each_unsafe_state(self):
        bad=[(0x0c000118,1<<20),(0x0c000318,1<<20),
             (0x10010024,0),(0x10010024,3),(0x10010018,0),(0x10010020,0)]
        for shift in (16,20,24):
            bad.append((0x100053b0,0x11110210&~(7<<shift)))
        for address,value in bad:
            values=self.good();values[address]=value
            with self.subTest(address=address,value=value):
                self.assertEqual(self.check(values)[0],0)

    def test_second_pass_change_rejected(self):
        for target in self.good():
            def change(address,value,n):
                if n>6 and address==target:
                    return value^(1<<20 if target in (0x0c000118,0x0c000318) else
                                  1<<16 if target==0x100053b0 else 1)
                return value
            with self.subTest(target=target):
                self.assertEqual(self.check(self.good(),change)[0],0)


if __name__=='__main__':
    unittest.main()
