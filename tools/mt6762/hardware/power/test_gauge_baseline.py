"""Host tests for the standalone, hardware-free fresh coefficient validator."""
import ctypes as C
import hashlib
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
U32=lambda value:struct.pack('>I',value)
def pad(value):return value+b'\0'*((-len(value))%4)
def node(name='',properties=(),children=()):return name,list(properties),list(children)
COMPATIBLES=[b'mediatek,MT6765\0',b'mediatek,mt6765-pwrap\0syscon\0',
             b'mediatek,mt6357\0',b'mediatek,mt6357-gauge\0']

def profile():
    nodes=[node(name,[('compatible',value)]) for name,value in zip(
        ['', 'pwrap@1000d000','main_pmic','mtk_gauge'],COMPATIBLES)]
    for parent,child in zip(nodes,nodes[1:]):parent[2].append(child)
    nodes[3][1].extend([('R_FG_VALUE',U32(10)),('CAR_TUNE_VALUE',U32(100))])
    return nodes

def fdt(tree):
    names={};strings=bytearray()
    def emit(part):
        name,properties,children=part;result=U32(1)+pad(name.encode()+b'\0')
        for key,value in properties:
            if key not in names:names[key]=len(strings);strings.extend(key.encode()+b'\0')
            result+=U32(3)+U32(len(value))+U32(names[key])+pad(value)
        return result+b''.join(emit(child) for child in children)+U32(2)
    structure=emit(tree)+U32(9)
    return struct.pack('>10I',0xd00dfeed,56+len(structure)+len(strings),56,
        56+len(structure),40,17,16,0,len(strings),len(structure))+b'\0'*16+structure+strings

class Baseline(C.Structure):
    _fields_=[(name,C.c_uint32) for name in ['version','fdt_size','dt_r_fg','dt_car_tune','r_fg','car_tune']]

class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        library=Path(cls.tmp.name)/'baseline.so'
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O2','-ffreestanding',
            '-shared','-fPIC',str(HERE/'mt6762_gauge_baseline.c'),'-o',str(library)],check=True)
        cls.lib=C.CDLL(str(library));cls.query=cls.lib.mt6762_gauge_baseline_from_fdt
        cls.query.argtypes=[C.c_void_p,C.c_size_t,C.POINTER(Baseline)];cls.query.restype=C.c_int

    def parse(self,data,accessible=None):
        data=bytes(data);buffer=C.create_string_buffer(data);out=Baseline()
        C.memset(C.byref(out),0xa5,C.sizeof(out))
        error=self.query(buffer,len(data) if accessible is None else accessible,C.byref(out))
        if error:self.assertEqual(bytes(out),b'\0'*C.sizeof(out))
        else:
            self.assertEqual((out.version,out.dt_r_fg,out.dt_car_tune,out.r_fg,out.car_tune),(1,10,100,100,1000))
            self.assertEqual(out.fdt_size,struct.unpack_from('>I',data,4)[0])
        return error,out

    def refuses(self,tree):self.assertNotEqual(self.parse(fdt(tree))[0],0)

    def test_exact_profile_and_property_order(self):
        nodes=profile();self.assertEqual(self.parse(fdt(nodes[0]))[0],0)
        nodes[3][1].reverse();nodes[0][2].insert(0,node('unrelated',[('status',b'disabled\0')]))
        self.assertEqual(self.parse(fdt(nodes[0]))[0],0)

    def test_every_ancestor_status(self):
        for depth in range(4):
            for status in [b'ok\0',b'okay\0']:
                nodes=profile();nodes[depth][1].append(('status',status))
                self.assertEqual(self.parse(fdt(nodes[0]))[0],0)
            for status in [b'disabled\0',b'reserved\0',b'fail\0',b'fail-sss\0',b'\0',b'okay',b'ok\0x',b'OK\0']:
                nodes=profile();nodes[depth][1].append(('status',status));self.refuses(nodes[0])
            nodes=profile();nodes[depth][1].extend([('status',b'ok\0')]*2);self.refuses(nodes[0])

    def test_missing_wrong_duplicate_and_malformed_compatible(self):
        for depth in range(4):
            nodes=profile();nodes[depth][1].pop(0);self.refuses(nodes[0])
            for value in [b'',b'\0',COMPATIBLES[depth][:-1],b'wrong\0',COMPATIBLES[depth]+b'extra\0']:
                nodes=profile();nodes[depth][1][0]=('compatible',value);self.refuses(nodes[0])
            nodes=profile();nodes[depth][1].append(nodes[depth][1][0]);self.refuses(nodes[0])

    def test_coefficients_require_present_exact_single_cells(self):
        for key in ['R_FG_VALUE','CAR_TUNE_VALUE']:
            nodes=profile();nodes[3][1][:]=[(k,v) for k,v in nodes[3][1] if k!=key];self.refuses(nodes[0])
            for value in [b'',b'\x0a',U32(0),U32(11),U32(101),U32(0xffffffff),U32(10)+U32(100),struct.pack('<I',10)]:
                nodes=profile();nodes[3][1][:]=[(k,value if k==key else v) for k,v in nodes[3][1]];self.refuses(nodes[0])
            nodes=profile();nodes[3][1].append(next(pair for pair in nodes[3][1] if pair[0]==key));self.refuses(nodes[0])

    def test_paths_duplicates_and_profile_elsewhere(self):
        for depth in range(1,4):
            nodes=profile();part=nodes[depth];nodes[depth-1][2][0]=node(part[0]+'@0',part[1],part[2]);self.refuses(nodes[0])
            nodes=profile();nodes[depth-1][2].append(nodes[depth]);self.refuses(nodes[0])
            # Even a second empty canonical ancestor makes path resolution ambiguous.
            nodes=profile();nodes[depth-1][2].append(node(nodes[depth][0]));self.refuses(nodes[0])
        nodes=profile();nodes[0][2].append(node('other-gauge',[('compatible',COMPATIBLES[3])]))
        self.refuses(nodes[0])
        nodes=profile();nodes[0][2].append(node('other-gauge',[('compatible',b'other\0'+COMPATIBLES[3])]))
        self.refuses(nodes[0])

    def test_header_and_every_accessible_truncation(self):
        data=fdt(profile()[0])
        for length in range(len(data)):self.assertNotEqual(self.parse(data,length)[0],0)
        for offset,values in {0:[0],4:[0,39,len(data)+1,0x80001,0xffffffff],8:[0,41,0xffffffff],
                12:[0,56,0xffffffff],16:[0,41,56,0xffffffff],20:[16,18],24:[0,15,18],
                32:[0,0xffffffff],36:[0,3,0xffffffff]}.items():
            for value in values:
                mutated=bytearray(data);struct.pack_into('>I',mutated,offset,value)
                self.assertNotEqual(self.parse(mutated)[0],0,(offset,value))
        output=Baseline();C.memset(C.byref(output),0xa5,C.sizeof(output))
        self.assertNotEqual(self.query(None,40,C.byref(output)),0);self.assertEqual(bytes(output),bytes(C.sizeof(output)))
        self.assertNotEqual(self.query(None,0,None),0)

    def test_structure_and_depth(self):
        data=bytearray(fdt(profile()[0]));structure=struct.unpack_from('>I',data,8)[0]
        mutated=data.copy();struct.pack_into('>I',mutated,structure,2);self.assertNotEqual(self.parse(mutated)[0],0)
        strings=struct.unpack_from('>I',data,12)[0]
        mutated=data.copy();struct.pack_into('>I',mutated,strings-4,4);self.assertNotEqual(self.parse(mutated)[0],0)
        # Reject a property after a child, even if all target fields were read.
        mutated=data.copy();mutated[strings-8:strings-4]=U32(3);self.assertNotEqual(self.parse(mutated)[0],0)
        deep=node('leaf')
        for _ in range(64):deep=node('nested',children=[deep])
        nodes=profile();nodes[0][2].append(deep);self.refuses(nodes[0])
        # Reserve map must terminate before the structure block.
        mutated=data.copy();mutated[40:56]=struct.pack('>QQ',0x40000000,0x1000)
        self.assertNotEqual(self.parse(mutated)[0],0)

    def test_deterministic_malformed_mutations_never_publish_other_values(self):
        data=fdt(profile()[0]);rng=random.Random(6762)
        for _ in range(1000):
            mutated=bytearray(data)
            for _ in range(rng.randrange(1,5)):
                index=rng.randrange(len(mutated));mutated[index]^=1<<rng.randrange(8)
            self.parse(mutated)

    def test_retained_real_dt_inputs(self):
        port=HERE.parents[4]
        sources={'firmware/boot.bin.dtb':'658e181d1a13d930dc09567883e734bdbd4579350c8332ff954a0ecbb2ed08fe',
            'hardware/trace-boot-20261025/capture30/runtime.dtb':'1c9bc7534bc3fd98950102d359c1e5d968263a1b1c059cb089874c9c8cdcc6ea'}
        if not all((port/name).exists() for name in sources):self.skipTest('retained physical DT inputs not present')
        for name,digest in sources.items():
            data=(port/name).read_bytes();self.assertEqual(hashlib.sha256(data).hexdigest(),digest)
            self.assertEqual(self.parse(data)[0],0,name)

if __name__=='__main__':unittest.main()
