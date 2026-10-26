"""Physical entry vectors, electrical/ownership refusals and read ordering."""
import ctypes as C
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
READ=C.CFUNCTYPE(C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint)

class ChargerEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        p=Path(cls.tmp.name)
        (p/'entry.c').write_text('#include "mt6762_charger_entry.h"\n'
            'int check(mt6762_charger_entry_read r,void *c,struct mt6762_charger_entry_failure *f)'
            '{return mt6762_charger_entry_detail(r,c,f);}\n'
            'unsigned region(unsigned n){return mt6762_charger_entry_base(n);}\n')
        subprocess.run(['cc','-std=c11','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
            '-I'+str(HERE),str(p/'entry.c'),'-o',str(p/'entry.so')],check=True)
        cls.lib=C.CDLL(str(p/'entry.so'))
        cls.lib.check.argtypes=[READ,C.c_void_p,C.c_void_p]
        cls.lib.region.argtypes=[C.c_uint];cls.lib.region.restype=C.c_uint32
        cls.fixture=json.loads((HERE/'physical-charger-entry-capture26.json').read_text())
        cls.rows={int(r['address'],0):r for r in cls.fixture['registers']}

    def run_entry(self,change=None):
        counts={};reads=[];errors=[];failure=(C.c_uint32*6)();context=0x1234
        def read(ctx,address,width):
            if ctx!=context or address not in self.rows:
                errors.append(('context/address',ctx,address));return 0xffffffff
            r=self.rows[address];passno=counts.get(address,0)
            if width!=r['width'] or passno>=2:
                errors.append(('width/pass',address,width,passno));return 0xffffffff
            counts[address]=passno+1;reads.append((address,width,passno))
            value=r['first' if passno==0 else 'second']
            return change(address,width,passno,value) if change else value
        result=self.lib.check(READ(read),context,failure)
        self.assertEqual(errors,[],'Invalid MMIO callback use')
        return result,reads,list(failure)

    def test_exact_two_pass_physical_capture_and_mapping(self):
        result,reads,_=self.run_entry();self.assertEqual(result,1)
        self.assertEqual(len(reads),88)
        self.assertEqual([(a,w) for a,w,p in reads[:44]],[(a,w) for a,w,p in reads[44:]])
        bases=[self.lib.region(i) for i in range(8)]
        self.assertEqual(len(set(bases)),8);self.assertEqual(self.lib.region(8),0)
        for a,w,_ in reads:
            self.assertEqual(sum(b<=a and a+w<=b+0x1000 for b in bases),1)
        # Pending interrupt is not acknowledged or even consulted; no FIFO,
        # CLEAR, SOFTRESET, DMA RESET/STOP, or command register is read.
        self.assertNotIn(0x0c000214,[a for a,_,_ in reads])
        for address in (0x11016000,0x11016038,0x11016040,0x1100058c,0x11000590,0x11000594):
            self.assertNotIn(address,[a for a,_,_ in reads])

    def test_dedicated_and_shared_gates_refuse_before_controller(self):
        for address,bits in [(0x100000a0,[0x80,1]),(0x10001090,[1<<11]),
                             (0x10001094,[1<<18]),(0x100010c8,[1<<18,1<<19,1<<20]),
                             (0x1000c26c,[1]),(0x1000c270,[1]),(0x1000c278,[2])]:
            for bit in bits:
                for bad_pass in (0,1):
                    with self.subTest(address=hex(address),bit=bit,passno=bad_pass):
                        result,reads,f=self.run_entry(lambda a,w,p,v:v^bit if a==address and p==bad_pass else v)
                        self.assertEqual(result,0);self.assertEqual((f[0],f[4]),(address,bad_pass))
                        self.assertFalse(any(a>=0x11000000 for a,w,p in reads if p==bad_pass))

    def test_unsafe_pads_irq_and_active_bus_refused(self):
        mutations=[(0x10005360,1),(0x10005010,1<<16),(0x10005210,1<<17),
            (0x10002610,1<<18),(0x10002650,8),(0x10002670,0x20),
            (0x10002690,8),(0x100026c0,1<<17),(0x0c000000,1<<31),
            (0x0c000114,4),(0x0c000314,4),(0x11016008,1),
            (0x1101600c,2),(0x11016024,1),(0x11000580,1),
            (0x11000584,1),(0x11000588,1),(0x11000598,1),
            (0x1100059c,4),(0x110005a0,4),(0x110005a4,1),
            (0x110005a8,1),(0x110005d4,1),(0x110005d8,1)]
        for address,bit in mutations:
            for bad_pass in (0,1):
                result,_,f=self.run_entry(lambda a,w,p,v:v^bit if a==address and p==bad_pass else v)
                with self.subTest(address=hex(address),passno=bad_pass):
                    self.assertEqual(result,0);self.assertEqual((f[0],f[4]),(address,bad_pass))

    def test_unrelated_pad_changes_are_ignored(self):
        # The captured DIN bit12 actually changed; only48/49 are relevant.
        self.assertNotEqual(self.rows[0x10005210]['first'],self.rows[0x10005210]['second'])
        for address,bit in [(0x10005210,1<<12),(0x10005010,1),(0x10005360,1<<8),
                            (0x10002650,1),(0x0c000114,8),(0x0c000314,8)]:
            self.assertEqual(self.run_entry(lambda a,w,p,v:v^bit if a==address else v)[0],1)

    def test_post_setup_values_are_not_entry_evidence(self):
        # Captured bus0 post-setup behavior and generic lab values must not
        # silently become the expected inherited bus5 entry state.
        for address,value in [(0x11016048,0x404),(0x11016030,0),
                              (0x11016020,0x419),(0x11016034,3),(0x1101604c,0x190)]:
            result,_,f=self.run_entry(lambda a,w,p,v:value if a==address else v)
            self.assertEqual(result,0);self.assertEqual(f[0],address)

    def test_null_or_missing_mapping_refused(self):
        self.assertEqual(self.lib.check(READ(),None,None),0)
        result,_,f=self.run_entry(lambda a,w,p,v:0xffffffff if a==0x11016048 else v)
        self.assertEqual(result,0);self.assertEqual(f,[0x11016048,0xffff,4,0xffffffff,0,2])

if __name__=='__main__':unittest.main()
