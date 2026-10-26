"""Exact live ADC routing/configuration admission; host only."""
import ctypes as C
import random
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_gauge_baseline import node, fdt, U32, COMPATIBLES

HERE=Path(__file__).resolve().parent
NAMES=b'pmic_battery_temp\0pmic_battery_voltage\0pmic_bif_voltage\0pmic_ptim_voltage\0pmic_ptim_r\0'
class Profile(C.Structure):
    _fields_=[(x,C.c_uint32) for x in ['version','fdt_size','phandle','channel','ratio_num','ratio_den','avg_num']]
def tree(phandle=39):
    nodes=[node(n,[('compatible',c)]) for n,c in zip(['','pwrap@1000d000','main_pmic','mtk_gauge'],COMPATIBLES)]
    for parent,child in zip(nodes[:2],nodes[1:3]):parent[2].append(child)
    nodes[2][2].append(nodes[3])
    nodes[3][1].extend([('io-channels',b''.join(U32(phandle)+U32(ch) for ch in [3,1,14,15,16])),('io-channel-names',NAMES)])
    adc=node('pmic_auxadc',[('compatible',b'mediatek,pmic-auxadc\0mediatek,mt6357-auxadc\0'),('phandle',U32(phandle)),('#io-channel-cells',U32(1))])
    channel=node('isense',[('channel',U32(1)),('resistance-ratio',U32(3)+U32(1)),('avg-num',U32(128))])
    adc[2].append(channel);nodes[2][2].append(adc)
    return nodes+[adc,channel]
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        path=Path(cls.tmp.name)
        (path/'entry.c').write_text('#include "mt6762_vbat_profile.h"\nint entry(const uint16_t *p){return mt6762_vbat_entry_ok(p);}\n')
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(HERE),str(HERE/'mt6762_vbat_fdt.c'),str(path/'entry.c'),'-o',str(path/'profile.so')],check=True)
        cls.lib=C.CDLL(str(path/'profile.so'));cls.query=cls.lib.mt6762_vbat_profile_from_fdt
        cls.query.argtypes=[C.c_void_p,C.c_size_t,C.POINTER(Profile)];cls.query.restype=C.c_int
        cls.lib.entry.argtypes=[C.POINTER(C.c_uint16)];cls.lib.entry.restype=C.c_int
    def parse(self,b,accessible=None):
        b=bytes(b);buf=C.create_string_buffer(b);out=Profile();C.memset(C.byref(out),0xa5,C.sizeof(out))
        error=self.query(buf,len(b) if accessible is None else accessible,C.byref(out))
        if error:self.assertEqual(bytes(out),bytes(C.sizeof(out)))
        else:self.assertEqual((out.version,out.channel,out.ratio_num,out.ratio_den,out.avg_num),(1,1,3,1,128))
        return error,out
    def rejects(self,nodes):self.assertNotEqual(self.parse(fdt(nodes[0]))[0],0)
    def test_valid_actual_route_and_order(self):
        for phandle in [1,39,0x10002]:
            nodes=tree(phandle);self.assertEqual(self.parse(fdt(nodes[0]))[1].phandle,phandle)
            nodes[2][2].reverse();nodes[4][1].reverse();nodes[5][1].reverse()
            self.assertEqual(self.parse(fdt(nodes[0]))[0],0)
    def test_required_fields(self):
        for depth in range(6):
            for index in range(len(tree()[depth][1])):
                nodes=tree();nodes[depth][1].pop(index);self.rejects(nodes)
                nodes=tree();nodes[depth][1].append(nodes[depth][1][index]);self.rejects(nodes)
                nodes=tree();key,value=nodes[depth][1][index];nodes[depth][1][index]=(key,value[:-1]);self.rejects(nodes)
    def test_disabled_or_ambiguous(self):
        for depth in range(6):
            for value in [b'disabled\0',b'ok',b'fail\0',b'OK\0',b'']:
                nodes=tree();nodes[depth][1].append(('status',value));self.rejects(nodes)
            nodes=tree();nodes[depth][1].append(('status',b'okay\0'));self.assertEqual(self.parse(fdt(nodes[0]))[0],0)
        nodes=tree();nodes[4][2].append(node('other',[('channel',U32(1))]));self.rejects(nodes)
        nodes=tree();nodes[0][2].append(node('other',[('phandle',U32(39))]));self.rejects(nodes)
        nodes=tree();nodes[0][2].append(node('other',[('linux,phandle',U32(39))]));self.rejects(nodes)
        nodes=tree();nodes[4][2].append(node('isense'));self.rejects(nodes)
        nodes=tree();nodes[0][2].append(node('other',[('compatible',b'mediatek,mt6357-auxadc\0')]));self.rejects(nodes)
    def test_wrong_mapping_and_cells(self):
        for index in range(10):
            nodes=tree();data=bytearray(nodes[3][1][1][1]);struct.pack_into('>I',data,4*index,99)
            nodes[3][1][1]=('io-channels',bytes(data));self.rejects(nodes)
        for depth,key,values in [(5,'channel',[0,2]),(5,'avg-num',[0,8,127,129]),(4,'#io-channel-cells',[0,2]),(4,'phandle',[0,40,0xffffffff])]:
            for value in values:
                nodes=tree();nodes[depth][1][:]=[(k,U32(value) if k==key else v) for k,v in nodes[depth][1]];self.rejects(nodes)
        nodes=tree();nodes[3][1][2]=('io-channel-names',NAMES.replace(b'pmic_battery_voltage',b'pmic_battery_unknown'));self.rejects(nodes)
    def test_bounds_and_mutations(self):
        b=fdt(tree()[0])
        for end in range(len(b)):self.assertNotEqual(self.parse(b,end)[0],0)
        for offset in [0,4,8,12,16,20,24,32,36]:
            q=bytearray(b);struct.pack_into('>I',q,offset,0xffffffff);self.assertNotEqual(self.parse(q)[0],0)
        rng=random.Random(6357)
        for _ in range(1000):
            q=bytearray(b)
            for _ in range(rng.randrange(1,4)):
                idx=rng.randrange(len(q));q[idx]^=1<<rng.randrange(8)
            self.parse(q)
    def test_live_capture44(self):
        port=HERE.parents[3].parents[2]
        for name in ['firmware/boot.bin.dtb','hardware/trace-boot-20261025/capture44/runtime.dtb']:
            data=(port/name).read_bytes();error,result=self.parse(data)
            self.assertEqual(error,0);self.assertEqual(result.phandle,39)
    def test_fixed_shadows_and_masks(self):
        expected=[0x5730,0x5730,0x7fca,0xf,0x14,0x372,0x8083,0x4000,0x30,0x6262,0x95d0,0x4055,1,0xfc0,0x38,0x1ac,0x4c,0xfdb,0xd,0xaa,0,0,0,0]
        def ok(values):return self.lib.entry((C.c_uint16*24)(*values))
        self.assertTrue(ok(expected));self.assertFalse(self.lib.entry(None))
        for i in range(19):
            for bit in range(16):
                v=expected.copy();v[i]^=1<<bit;self.assertFalse(ok(v))
        for i,mask in [(19,0x3ff),(20,7),(21,0xff),(22,0x3449),(23,0x500)]:
            for bit in range(16):
                v=expected.copy();v[i]^=1<<bit;self.assertEqual(bool(ok(v)),not bool(mask&(1<<bit)))
if __name__=='__main__':unittest.main()
