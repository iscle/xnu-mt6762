"""Measured-entry admission, including gate-first refusal and changing state."""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
READ=C.CFUNCTYPE(C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint)

class NativeTouchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        p=Path(cls.tmp.name)
        (p/'t.c').write_text('#include "mt6762_touch_entry.h"\n'
            'int check(mt6762_entry_read r){return mt6762_touch_entry_ok(r,0);}\n'
            'unsigned region(unsigned n){return mt6762_touch_entry_base(n);}\n'
            'int detail(mt6762_entry_read r,void *f){return mt6762_touch_entry_detail(r,0,f);}\n')
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
            '-I'+str(HERE.parent/'hardware/display-touch'),str(p/'t.c'),'-o',str(p/'t.so')],check=True)
        cls.lib=C.CDLL(str(p/'t.so'));cls.lib.check.argtypes=[READ]
        cls.lib.region.argtypes=[C.c_uint];cls.lib.region.restype=C.c_uint32
        cls.lib.detail.argtypes=[READ,C.c_void_p]
    def check(self,values,change=None):
        reads=[]
        def read(ctx,a,w):
            reads.append((a,w));value=values.get(a,0)
            return change(a,w,value,len(reads)) if change else value
        result=self.lib.check(READ(read))
        return result,reads
    def good(self):
        return {0x100000a0:2,0x1000c26c:0xff800081,0x1000c270:0x180000,0x1000c278:0x80000001,
            0x100053a0:0x1100,0x10005220:3<<18,0x10002a30:0x1400000,0x10002a50:0x1400000,
            0x10002a80:0xa00,0x10005050:1<<14,0x10005150:1<<14,0x10005250:1<<14,
            0x10005200:1,0x1000b080:1}
    def test_valid_and_gate_first_refusal(self):
        good=self.good();result,reads=self.check(good);self.assertEqual(result,1)
        self.assertEqual(reads[:len(reads)//2],reads[len(reads)//2:])
        for a,w in reads:self.assertEqual(w,2 if a in (0x11007024,0x1100700c) else 4)
        regions=[self.lib.region(i) for i in range(9)]
        self.assertEqual(self.lib.region(9),0)
        self.assertEqual(len(set(regions)),9)
        for a,w in reads:
            self.assertEqual(sum(base<=a and a+w<=base+0x1000 for base in regions),1,
                             'Kernel entry mappings must cover each complete read, including INFRA')
        good[0x100000a0]|=0x80;result,reads=self.check(good)
        self.assertEqual(result,0);self.assertEqual(reads,[(0x100000a0,4)])
    def test_unsafe_reset_irq_active_transfer_and_clock_change(self):
        for a,value in [(0x10005050,0),(0x10005150,0),(0x100053a0,0),(0x10002a40,1<<24),
                        (0x1000b080,0),(0x1000b400,1),(0xc00030c,1<<20),
                        (0x11007024,1),(0x11000088,1),(0x110000d8,1)]:
            good=self.good();good[a]=value
            with self.subTest(address=hex(a)):self.assertEqual(self.check(good)[0],0)
        def change(a,w,v,n):return v^1 if a==0x100000a0 and n>1 else v
        self.assertEqual(self.check(self.good(),change)[0],0)
    def test_failure_identifies_missing_infra_mapping(self):
        values=self.good();values[0x10001090]=0xffffffff
        failure=(C.c_uint32*6)()
        result=self.lib.detail(READ(lambda ctx,a,w:values.get(a,0)),failure)
        self.assertEqual(result,0)
        self.assertEqual(list(failure),[0x10001090,1<<11,0,0xffffffff,0,4])
    @unittest.skipUnless(os.environ.get('MTK_PERIPHERAL_CAPTURE'),'private physical snapshot optional')
    def test_actual_captured_values(self):
        data=json.loads(Path(os.environ['MTK_PERIPHERAL_CAPTURE']).read_text())
        self.assertEqual(data['state'],2)
        for name in ('first','second'):
            self.assertEqual(self.check({int(e['address'],0):e[name] for e in data['registers'] if e[name] is not None})[0],1)

if __name__=='__main__':unittest.main()
