"""Exercise the actual passive reader with width-checked MMIO callbacks."""
import ctypes as C
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import peripheral_record as record

HERE=Path(__file__).resolve().parent
READ=C.CFUNCTYPE(C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint)
BARRIER=C.CFUNCTYPE(None,C.c_void_p)
TICKS=C.CFUNCTYPE(C.c_uint64,C.c_void_p)
class IO(C.Structure):
    _fields_=[('context',C.c_void_p),('read',READ),('barrier',BARRIER),('ticks',TICKS)]

class PeripheralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        path=Path(cls.tmp.name)
        (path/'test.c').write_text('#include "peripheral_probe.h"\nvoid capture(const struct peripheral_io *io,void *r){peripheral_capture(io,r);}\n')
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O2','-shared','-fPIC',
                        '-I'+str(HERE),str(path/'test.c'),'-o',str(path/'test.so')],check=True)
        cls.lib=C.CDLL(str(path/'test.so'));cls.lib.capture.argtypes=[C.POINTER(IO),C.c_void_p]
    def capture(self,values):
        identity=bytes(range(32));raw=C.create_string_buffer(record.initialized(identity))
        table={int(e['address'],0):e for e in record.registers()}
        reads=[];errors=[];ticks=[0]
        def read(ctx,address,width):
            if address not in table or table[address]['width']!=width:errors.append((address,width))
            reads.append(address)
            return values.get(address,0)
        def time(ctx):ticks[0]+=1;return ticks[0]
        io=IO(None,READ(read),BARRIER(lambda ctx:None),TICKS(time))
        self.lib.capture(C.byref(io),raw)
        self.assertEqual(errors,[])
        data=raw.raw[:record.SIZE]
        return data,record.decode(data,identity),reads
    def test_gated_blocks_are_skipped_on_both_passes(self):
        _,decoded,reads=self.capture({0x10001090:0xffffffff,0x10001094:0xffffffff,0x100010c8:0xffffffff})
        expected=[int(e['address'],0) for e in record.registers() if e['group'] in (0,5)]
        self.assertEqual(reads,expected*2)
        self.assertEqual(decoded['state'],2)
        for e in decoded['registers']:self.assertEqual(e['valid'],3 if e['group'] in (0,5) else 0)
    def test_clocked_blocks_and_register_widths(self):
        values={0x10000070:0x101}
        for a in (0x1000c23c,0x1000c27c):
            values.update({a:0x800001,a+4:0x100000,a+12:1})
        _,decoded,reads=self.capture(values)
        self.assertEqual(reads,[int(e['address'],0) for e in record.registers()]*2)
        self.assertTrue(all(e['valid']==3 for e in decoded['registers']))
        # DATA_PORT, PWRAP command/clear and MSDC FIFO reads are forbidden.
        for forbidden in (0x11007000,0x1000dc20,0x1000dc28,0x1123001c):
            self.assertNotIn(forbidden,reads)
        # No card CID, CSD, raw EXT_CSD or pointer-directed RAM reads.
        self.assertNotIn(0x48146d84,reads)
        self.assertTrue(all(a<0x48146d84 for a in reads))
    def test_lk_card_metadata_and_rejections(self):
        words=(0x4a0301c3,0x00c0eb03,0x4410447a,0xbf004770,0xfb12c,
               0x4a030203,0x2080ebc3,0x4410447a,0xbf004770,0xfb228)
        values={0x4804bb18+4*n:v for n,v in enumerate(words)}
        host,card=0x48146c50,0x48146d60
        values.update({host:card,host+0x28:0x11230000,host+0x44:512,
                       card:host,card+4:244285440,card+8:512,card+12:0xc0ff8080,
                       card+24:1,card+28:1,card+32:0x10011})
        _,decoded,reads=self.capture(values)
        self.assertTrue(decoded['lk_card_metadata']['valid'])
        self.assertEqual(decoded['lk_card_metadata']['rca'],1)
        for address,value in ((host,0),(host+0x28,0),(host+0x44,1024),(card,0),
                              (card+4,0),(card+8,1024),(card+12,0x80ff8080),
                              (card+24,0),(card+24,65536),(card+28,2),
                              (card+32,0x11),(0x4804bb28,0)):
            with self.subTest(address=hex(address),value=value):
                _,bad,_=self.capture(values|{address:value})
                self.assertFalse(bad['lk_card_metadata']['valid'])
        unstable=decoded['registers']
        next(e for e in unstable if int(e['address'],0)==card+24)['stable']=False
        self.assertFalse(record.lk_card_metadata(unstable)['valid'])
    def test_missing_pll_power_prevents_msdc_access(self):
        _,decoded,_=self.capture({0x10000070:0x101,0x1000c23c:0x800001,0x1000c240:1,
                                  0x1000c248:1,0x1000c27c:1,0x1000c280:1,0x1000c288:3})
        self.assertTrue(all(e['valid']==0 for e in decoded['registers'] if e['group']==4))
    def test_decoder_rejects_identity_allowlist_and_false_completion(self):
        data,_,_=self.capture({0x10001090:0xffffffff})
        identity=bytes(range(32))
        for offset,value,fmt in ((16,255,'B'),(48,3,'I'),(52,0,'I'),(56,1,'I'),
                                 (60,249,'I'),(96,0x11007000,'I'),(100,1,'B'),(102,4,'H')):
            bad=bytearray(data);struct.pack_into('<'+fmt,bad,offset,value)
            with self.subTest(offset=offset),self.assertRaises(ValueError):record.decode(bytes(bad),identity)
        bad=bytearray(record.initialized(identity));bad[104]=1
        with self.assertRaises(ValueError):record.decode(bytes(bad),identity)

if __name__=='__main__':unittest.main()
