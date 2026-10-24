#!/usr/bin/env python3
"""Freestanding parser exercised through a host shared object; no device I/O."""
import ctypes as C
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
U32=lambda x:struct.pack('>I',x)
U64=lambda x:struct.pack('>Q',x)
def padded(b): return b+b'\0'*((-len(b))%4)
def node(name='', props=(), children=()): return name,props,children

def fdt(tree=None, reservations=()):
    if tree is None:
        tree=node('', [('#address-cells',U32(2)),('#size-cells',U32(2))],
            [node('memory@40000000',[('device_type',b'memory\0'),('reg',U64(0x40000000)+U64(0xc0000000))])])
    names={}; strings=bytearray()
    def emit(n):
        name,props,children=n
        result=U32(1)+padded(name.encode()+b'\0')
        for k,v in props:
            if k not in names: names[k]=len(strings); strings.extend(k.encode()+b'\0')
            result+=U32(3)+U32(len(v))+U32(names[k])+padded(v)
        for child in children: result+=emit(child)
        return result+U32(2)
    structure=emit(tree)+U32(9)
    reserve=b''.join(U64(a)+U64(n) for a,n in reservations)+b'\0'*16
    so=40+len(reserve); to=so+len(structure); total=to+len(strings)
    return struct.pack('>10I',0xd00dfeed,total,so,to,40,17,16,0,len(strings),len(structure))+reserve+structure+strings

class Range(C.Structure): _fields_=[('base',C.c_uint64),('size',C.c_uint64)]
class Framebuffer(C.Structure): _fields_=[('base',C.c_uint64),('size',C.c_uint64),('width',C.c_uint32),('height',C.c_uint32),('stride',C.c_uint32),('present',C.c_uint32),('found',C.c_uint32),('fps',C.c_uint32)]
class Info(C.Structure): _fields_=[('memory',Range*16),('reserved',Range*64),('reserved_kind',C.c_uint8*64),('memory_count',C.c_uint32),('reserved_count',C.c_uint32),('total_size',C.c_uint32),('board_compatible',C.c_uint32),('framebuffer',Framebuffer)]

class FDTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        lib=Path(cls.tmp.name)/'fdt.so'
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding','-shared','-fPIC',str(HERE/'fdt_handoff.c'),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib))
        cls.lib.mtk_fdt_parse.argtypes=[C.c_void_p,C.c_size_t,C.POINTER(Info)]
        cls.lib.mtk_fdt_framebuffer_reserved.argtypes=[C.POINTER(Info)]
        cls.lib.mtk_fdt_select_window.argtypes=[C.POINTER(Info),C.c_uint64,C.POINTER(Range),C.c_size_t,C.POINTER(C.c_uint64)]
    def parse(self,b,accessible=None):
        info=Info(); C.memset(C.byref(info),0xa5,C.sizeof(info)); buf=C.create_string_buffer(b)
        rc=self.lib.mtk_fdt_parse(buf,len(b) if accessible is None else accessible,C.byref(info))
        if rc:self.assertEqual(bytes(info),b'\0'*C.sizeof(info))
        return rc,info
    def select(self,info,fdt_pa=0x42000000,excluded=()):
        array=(Range*len(excluded))(*(Range(a,n) for a,n in excluded)); base=C.c_uint64(0xdead)
        rc=self.lib.mtk_fdt_select_window(C.byref(info),fdt_pa,array,len(excluded),C.byref(base))
        return rc,base.value
    def root(self,banks,extra=(),cells=(2,2)):
        return node('',[('#address-cells',U32(cells[0])),('#size-cells',U32(cells[1]))],
            [node('memory',[('device_type',b'memory\0'),('reg',b''.join(U64(a)+U64(n) for a,n in banks))])]+list(extra))
    def test_live_three_gib_map_selects_allowed_window(self):
        rc,i=self.parse(fdt()); self.assertEqual(rc,0); self.assertEqual(i.memory_count,1)
        self.assertEqual(self.select(i),(0,0x80000000))
    def test_static_stock_map_has_no_window(self):
        rc,i=self.parse(fdt(self.root([(0x40000000,0x20000000)])))
        self.assertEqual(rc,0); self.assertEqual(self.select(i),(-8,0))
        stock=HERE.parents[3]/'firmware/boot.bin.dtb'
        if stock.exists():
            rc,i=self.parse(stock.read_bytes()); self.assertEqual(rc,0)
            self.assertEqual(i.board_compatible,1)
            self.assertEqual(self.select(i),(-8,0))
            self.assertEqual(i.reserved_count,6)
    def test_reservations_source_fdt_and_alignment(self):
        reserve=node('reserved-memory',[('#address-cells',U32(2)),('#size-cells',U32(2)),('ranges',b'')],
            [node('tee@a0000000',[('reg',U64(0xa0000000)+U64(0x200000))])])
        rc,i=self.parse(fdt(self.root([(0x40000000,0xc0000000)],[reserve]),[(0x80000000,0x20000000)]))
        self.assertEqual(rc,0); self.assertEqual(i.reserved_count,2)
        self.assertEqual(self.select(i,0xa0200000,[(0xa0400000,0x1000)]),(0,0xa0600000))
    def test_fragmented_banks_do_not_join_across_hole(self):
        rc,i=self.parse(fdt(self.root([(0x80000000,0x10000000),(0x90200000,0x10000000)])))
        self.assertEqual(rc,0); self.assertEqual(self.select(i),(-8,0))
    def test_bank_order_and_four_gib_limit(self):
        rc,i=self.parse(fdt(self.root([(0xc0000000,0x60000000),(0x80000000,0x20000000)])))
        self.assertEqual(rc,0); self.assertEqual(self.select(i),(0,0x80000000))
        rc,i=self.parse(fdt(self.root([(0xe0200000,0x60000000)])))
        self.assertEqual(rc,0); self.assertEqual(self.select(i),(-8,0))
    def test_every_truncated_prefix(self):
        b=fdt()
        for length in range(len(b)):
            rc,_=self.parse(b[:length]); self.assertNotEqual(rc,0,length)
    def test_bad_header_offsets_overlap_and_size(self):
        original=fdt()
        for offset,value in [(0,0),(4,0x200001),(8,41),(8,len(original)-4),(12,56),(16,41),(16,len(original)-8),(20,16),(24,18),(32,0xffffffff),(36,0xfffffffc)]:
            b=bytearray(original);b[offset:offset+4]=U32(value)
            self.assertNotEqual(self.parse(bytes(b))[0],0,(offset,value))
    def test_unknown_cells_rejected(self):
        for cells in [(1,2),(2,1),(3,2),(2,0)]:self.assertNotEqual(self.parse(fdt(self.root([(0x80000000,0x80000000)],cells=cells)))[0],0)
        reserve=node('reserved-memory',[('#address-cells',U32(1)),('#size-cells',U32(2)),('ranges',b'')],[node('range',[('reg',U64(0x80000000)+U64(0x1000))])])
        self.assertEqual(self.parse(fdt(self.root([(0x80000000,0x80000000)],[reserve])))[0],-4)
    def test_overflow_zero_overlap_and_limits(self):
        for banks,expected in [([(0xfffffffffffffff0,0x20)],-5), ([(0x80000000,0)],-5),
                ([(0x80000000,0x40000000),(0xa0000000,0x20000000)],-7),
                ([(0x80000000+n*0x200000,0x200000) for n in range(17)],-6)]:
            self.assertEqual(self.parse(fdt(self.root(banks)))[0],expected)
        self.assertEqual(self.parse(fdt(reservations=[(n*0x1000,0x1000) for n in range(65)]))[0],-6)
    def test_missing_reserved_reg_or_translated_ranges(self):
        for props,child in [([('ranges',b'')],node('dynamic',[('size',U64(0x1000))])),
                ([('ranges',U64(1))],node('region',[('reg',U64(1)+U64(0x1000))]))]:
            reserve=node('reserved-memory',[('#address-cells',U32(2)),('#size-cells',U32(2))]+props,[child])
            self.assertNotEqual(self.parse(fdt(self.root([(0x80000000,0x80000000)],[reserve])))[0],0)
    def test_optional_framebuffer_information_only(self):
        fb=node('framebuffer@c0000000',[('reg',U64(0xc0000000)+U64(0x200000)),('width',U32(384)),('height',U32(854)),('stride',U32(1536))])
        chosen=node('chosen',[('#address-cells',U32(2)),('#size-cells',U32(2))],[fb])
        rc,i=self.parse(fdt(self.root([(0x80000000,0x80000000)],[chosen])))
        self.assertEqual(rc,0);self.assertEqual(i.framebuffer.present,15)
        self.assertEqual((i.framebuffer.base,i.framebuffer.width,i.framebuffer.height,i.framebuffer.stride),(0xc0000000,384,854,1536))
        self.assertEqual(self.select(i),(0,0x80000000))
    def test_structure_tokens_strings_duplicates_and_depth(self):
        b=bytearray(fdt());so=struct.unpack_from('>I',b,8)[0];b[so:so+4]=U32(99)
        self.assertNotEqual(self.parse(bytes(b))[0],0)
        b=bytearray(fdt());b[-1]=65;self.assertNotEqual(self.parse(bytes(b))[0],0)
        duplicate=node('',[('#address-cells',U32(2)),('#address-cells',U32(2)),('#size-cells',U32(2))],[])
        self.assertNotEqual(self.parse(fdt(duplicate))[0],0)
        deep=node('leaf')
        for _ in range(65):deep=node('bus',[],[deep])
        self.assertEqual(self.parse(fdt(self.root([(0x80000000,0x80000000)],[deep])))[0],-3)
    def test_lk_videolfb_little_endian_and_conflicts(self):
        tag=struct.pack('<QIII',0xc0000000,1,6000,0x200000)+b'panel\0\0\0'
        props=[('atag,videolfb',tag)]
        rc,i=self.parse(fdt(self.root([(0x80000000,0x80000000)],[node('chosen',props)])))
        self.assertEqual(rc,0); self.assertEqual((i.framebuffer.base,i.framebuffer.size,i.framebuffer.found,i.framebuffer.fps),(0xc0000000,0x200000,1,6000))
        self.assertEqual((i.framebuffer.width,i.framebuffer.height,i.framebuffer.stride),(0,0,0))
        for extras in [[('videolfb-base_h',U32(0)),('videolfb-base_l',U32(0xc0200000)),('videolfb-vramSize',U32(0x200000))],
                [('atag,videolfb',tag)], [('videolfb-base_h',U32(0))]]:
            self.assertNotEqual(self.parse(fdt(self.root([(0x80000000,0x80000000)],[node('chosen',props+extras)])))[0],0)
        malformed=struct.pack('<QIII',0xc0000000,1,6000,0x200000)+b'xxxx'
        self.assertNotEqual(self.parse(fdt(self.root([(0x80000000,0x80000000)],[node('chosen',[('atag,videolfb',malformed)])])))[0],0)

    def test_dynamic_alloc_ranges_are_fully_excluded(self):
        dynamic=node('reserved-memory',[('#address-cells',U32(2)),('#size-cells',U32(2)),('ranges',b'')],[
            node('a',[('size',U64(0x1000)),('alloc-ranges',U64(0x40000000)+U64(0x80000000))]),
            node('b',[('size',U64(0x1000)),('alloc-range',U64(0xc0000000)+U64(0x10000000))]),
            node('overlap',[('size',U64(0x1000)),('alloc-ranges',U64(0x80000000)+U64(0x20000000))])])
        rc,i=self.parse(fdt(self.root([(0x40000000,0x180000000)],[dynamic])))
        self.assertEqual(rc,0);self.assertEqual(i.reserved_count,3)
        self.assertEqual(self.select(i),(0,0xd0000000))
    def test_board_compatible_exact_list(self):
        for values,expected in [(b'board,test\0mediatek,MT6765\0',1),(b'mediatek,MT6762\0',1),
                (b'mediatek,mt6765\0',0),(b'mediatek,MT6765-other\0',0)]:
            tree=self.root([(0x80000000,0x80000000)])
            rc,i=self.parse(fdt(node(tree[0],list(tree[1])+[('compatible',values)],tree[2])))
            self.assertEqual(rc,0);self.assertEqual(i.board_compatible,expected)

    def test_memreserve_terminator_and_property_string_bounds(self):
        b=bytearray(fdt()); b[40:56]=U64(0x40000000)+U64(0x1000)
        self.assertEqual(self.parse(bytes(b))[0],-2)
        b=bytearray(fdt()); so=struct.unpack_from('>I',b,8)[0]
        # Root token/name occupy8bytes; first property's name offset follows token+length.
        b[so+16:so+20]=U32(0xffffffff)
        self.assertEqual(self.parse(bytes(b))[0],-2)
    def test_all_single_byte_mutations_remain_bounded(self):
        original=fdt()
        for offset in range(len(original)):
            b=bytearray(original); b[offset]^=0xff
            rc,i=self.parse(bytes(b))
            self.assertIn(rc,range(-8,1))
            if rc==0:
                result,address=self.select(i)
                self.assertIn(result,(0,-8))
                if result==0:
                    self.assertGreaterEqual(address,0x80000000)
                    self.assertLessEqual(address+0x20000000,0x100000000)
                    self.assertEqual(address%0x200000,0)

    def test_framebuffer_requires_actual_independent_reservation_in_ram(self):
        tag=struct.pack('<QIII',0xc0000000,1,6000,0x200000)+b'panel\0\0\0'
        chosen=node('chosen',[('atag,videolfb',tag)])
        for kind,prop,expected in [(2,'reg',1),(3,'alloc-ranges',0)]:
            reserve=node('reserved-memory',[('#address-cells',U32(2)),('#size-cells',U32(2)),('ranges',b'')],
                [node('fb',[(prop,U64(0xc0000000)+U64(0x200000))])])
            rc,i=self.parse(fdt(self.root([(0x80000000,0x80000000)],[chosen,reserve])))
            self.assertEqual(rc,0);self.assertEqual(i.reserved_kind[0],kind)
            self.assertEqual(self.lib.mtk_fdt_framebuffer_reserved(C.byref(i)),expected)
        rc,i=self.parse(fdt(self.root([(0x80000000,0x80000000)],[chosen]),[(0xc0000000,0x200000)]))
        self.assertEqual(rc,0);self.assertEqual(i.reserved_kind[0],1)
        self.assertEqual(self.lib.mtk_fdt_framebuffer_reserved(C.byref(i)),1)
        rc,i=self.parse(fdt(self.root([(0x80000000,0x80000000)],[chosen])))
        self.assertEqual(rc,0);self.assertEqual(i.reserved_count,0)
        self.assertEqual(self.lib.mtk_fdt_framebuffer_reserved(C.byref(i)),0)
        rc,i=self.parse(fdt(self.root([(0x80000000,0x20000000)],[chosen]),[(0xc0000000,0x200000)]))
        self.assertEqual(rc,0);self.assertEqual(self.lib.mtk_fdt_framebuffer_reserved(C.byref(i)),0)

    def test_invalid_exclusions(self):
        rc,i=self.parse(fdt());self.assertEqual(rc,0)
        self.assertEqual(self.select(i,0xffffffffffffffff)[0],-5)
        self.assertEqual(self.select(i,excluded=[(1,0)])[0],-5)
        self.assertEqual(self.select(i,excluded=[(0xfffffffffffffff0,0x100)])[0],-5)
        self.assertEqual(self.select(i,excluded=[(0x80000000,0x80000000)]),(-8,0))

if __name__=='__main__':unittest.main()
