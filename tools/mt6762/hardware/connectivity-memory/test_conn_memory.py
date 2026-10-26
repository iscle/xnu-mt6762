#!/usr/bin/env python3
"""Compile the actual freestanding C core; all memory is host-owned synthetic data."""
import ctypes as C
import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fdt_test_helpers', HERE/'../../physical/test_fdt_handoff.py')
F=importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
Range, Info = F.Range, F.Info
class Table(C.Structure):
    _fields_=[('free',Range*128),('reserved',Range*128),('free_count',C.c_uint32),('reserved_count',C.c_uint32),('free_bytes',C.c_uint64),('reserved_bytes',C.c_uint64),('bank_bytes',C.c_uint64)]
class Request(C.Structure):
    _fields_=[('enabled',C.c_uint32),('reserved_zero',C.c_uint32),('boot_nonce',C.c_uint64),('fdt_pa',C.c_uint64),('source_image',Range),('kernel_managed',Range),('loader_live',Range),('additional',C.POINTER(Range)),('additional_count',C.c_size_t)]
class Ledger(C.Structure):
    _fields_=[('version',C.c_uint32),('count',C.c_uint32),('boot_nonce',C.c_uint64),('fdt_pa',C.c_uint64),('fdt_bytes',C.c_uint64),('proposed',Range*2),('bank_bytes',C.c_uint64),('free_bytes',C.c_uint64),('lk_reserved_bytes',C.c_uint64),('lk_free_count',C.c_uint32),('lk_reserved_count',C.c_uint32)]
class Workspace(C.Structure):
    _fields_=[('info',Info),('table',Table),('allowed',(Range*16)*2),('other_dynamic',Range*64),('allowed_count',C.c_uint32*2),('other_count',C.c_uint32)]

def mblock(free=((0x40000000,0x180000000,0),), reserved=()):
    b=bytearray(22552);struct.pack_into('<I',b,0,len(free))
    for i,(a,n,r) in enumerate(free):struct.pack_into('<QQI',b,8+i*24,a,n,r)
    struct.pack_into('<III',b,3080,0x99999999,2,len(reserved))
    for i,(a,n,m,name) in enumerate(reserved):
        p=3096+i*152;struct.pack_into('<QQI',b,p,a,n,m);b[p+20:p+20+len(name)]=name.encode()
    return bytes(b)
def target(name,size,allowed=((0x40000000,0x80000000),), extra=(), omit=()):
    props=[('compatible',b'mediatek,consys-reserve-memory\0' if name=='consys-reserve-memory' else b'shared-dma-pool\0'),('no-map',b''),('size',F.U64(size)),('alignment',F.U64(0x1000000)),('alloc-ranges',b''.join(F.U64(a)+F.U64(n) for a,n in allowed))]
    return F.node(name,[(k,v) for k,v in props if k not in omit]+list(extra))
def tree(table=None,banks=((0x40000000,0x180000000),),extra=(),targets=None,memory_extra=()):
    if targets is None:targets=[target('consys-reserve-memory',0x400000),target('wifi-reserve-memory',0x300000)]
    return F.fdt(F.node('',[('#address-cells',F.U32(2)),('#size-cells',F.U32(2)),('compatible',b'mediatek,MT6765\0')],[
        F.node('memory',[('device_type',b'memory\0'),('reg',b''.join(F.U64(a)+F.U64(n) for a,n in banks)),('mblock_info',mblock() if table is None else table)]+list(memory_extra)),
        F.node('reserved-memory',[('#address-cells',F.U32(2)),('#size-cells',F.U32(2)),('ranges',b'')],list(targets)+list(extra))]))

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        so=Path(cls.tmp.name)/'core.so'
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding','-shared','-fPIC',str(HERE/'conn_memory.c'),str(HERE/'../../physical/fdt_handoff.c'),'-o',str(so)],check=True)
        cls.lib=C.CDLL(str(so))
        cls.lib.cm_parse_mblock.argtypes=[C.c_void_p,C.c_size_t,C.POINTER(Range),C.c_size_t,C.POINTER(Table)]
        cls.lib.cm_plan.argtypes=[C.c_void_p,C.c_size_t,C.POINTER(Request),C.POINTER(Workspace),C.POINTER(Ledger)]
    def parse(self,b,banks=((0x40000000,0x180000000),)):
        bs=(Range*len(banks))(*(Range(a,n) for a,n in banks));out=Table();C.memset(C.byref(out),0xa5,C.sizeof(out))
        rc=self.lib.cm_parse_mblock(C.create_string_buffer(b),len(b),bs,len(bs),C.byref(out))
        if rc:self.assertEqual(bytes(out),bytes(C.sizeof(out)))
        return rc,out
    def plan(self,b=None,extra=(),**kw):
        b=tree() if b is None else b;buf=C.create_string_buffer(b);before=bytes(buf)
        ex=(Range*len(extra))(*(Range(a,n) for a,n in extra))
        r=Request(1,0,0x12345678,0x47880000,Range(0x40080000,0x7800000),Range(0xd0000000,0xefe00000),Range(0x40080000,0x100000),ex,len(ex))
        for k,v in kw.items():setattr(r,k,v)
        w=Workspace();out=Ledger();C.memset(C.byref(out),0xa5,C.sizeof(out))
        rc=self.lib.cm_plan(buf,len(b),C.byref(r),C.byref(w),C.byref(out))
        self.assertEqual(bytes(buf),before)
        if rc:self.assertEqual(bytes(out),bytes(C.sizeof(out)))
        return rc,out,w
    def test_six_gib_partition(self):
        rc,t=self.parse(mblock());self.assertEqual(rc,0);self.assertEqual(t.bank_bytes,6<<30)
    def test_complete_two_bank_partition_parameterized(self):
        rc,t=self.parse(mblock(((0x40000000,0x10000000,0),(0x80000000,0x20000000,1))),((0x40000000,0x10000000),(0x80000000,0x20000000)))
        self.assertEqual(rc,0);self.assertEqual(t.bank_bytes,0x30000000)
    def test_empty_free_slot_supported(self):
        self.assertEqual(self.parse(mblock(((0x40000000,0,0),(0x40000000,0x180000000,1))))[0],0)
    def test_exact_length_magic_version_endianness(self):
        b=mblock()
        for bad in [b[:-1],b+b'\0',b[:3080]+bytes(4)+b[3084:],b[:3084]+struct.pack('<I',1)+b[3088:],struct.pack('>I',1)+b[4:]]:
            with self.subTest(size=len(bad)):self.assertNotEqual(self.parse(bad)[0],0)
    def test_count_bounds(self):
        for off in [0,3088]:
            b=bytearray(mblock());struct.pack_into('<I',b,off,129);self.assertEqual(self.parse(bytes(b))[0],-5)
    def test_free_overlap_reserved_overlap_and_cross_overlap(self):
        cases=[mblock(((0x40000000,0x180000000,0),(0x80000000,0x1000,0))),mblock((),((0x40000000,0x180000000,0,'a'),(0x80000000,0x1000,1,'b'))),mblock(reserved=((0x80000000,0x1000,0,'a'),))]
        for b in cases:self.assertEqual(self.parse(b)[0],-7)
    def test_gap_and_bank_overflow_reject(self):
        self.assertEqual(self.parse(mblock(((0x40000000,0x17ffff000,0),)))[0],-8)
        self.assertEqual(self.parse(mblock(((0xfffffffffffffff0,0x100,0),)))[0],-6)
        self.assertNotEqual(self.parse(mblock(),((0xfffffffffffffff0,0x100),))[0],0)
    def test_bad_rank_mapping_name_and_empty_reserved(self):
        for b in [mblock(((0x40000000,0x180000000,4),)),mblock((),((0x40000000,0x180000000,2,'a'),)),mblock((),((0x40000000,0x180000000,0,''),)),mblock((),((0x40000000,0x180000000,0,'a'*128),)),mblock(reserved=((0x40000000,0,0,'a'),))]:
            self.assertNotEqual(self.parse(b)[0],0)
    def test_disabled_and_missing_required_live_inputs(self):
        for kw in [{'enabled':0},{'enabled':2},{'boot_nonce':0},{'reserved_zero':1},{'source_image':Range(0,0)},{'kernel_managed':Range(0,0)},{'loader_live':Range(0,0)}]:
            self.assertNotEqual(self.plan(**kw)[0],0)
    def test_exclusions_and_exact_sizes(self):
        rc,o,w=self.plan(extra=[(0x48000000,0x58000000)])
        self.assertEqual(rc,0);self.assertEqual([(x.base,x.size) for x in o.proposed],[(0xa0000000,0x400000),(0xa1000000,0x300000)])
        self.assertEqual(o.boot_nonce,0x12345678);self.assertEqual(o.version,1)
        self.assertEqual(w.table.bank_bytes,0x180000000)
    def test_unrelated_dynamic_with_identical_target_range_is_not_removed(self):
        other=F.node('different-owner',[('size',F.U64(0x1000)),('alloc-ranges',F.U64(0x40000000)+F.U64(0x80000000))])
        self.assertEqual(self.plan(tree(extra=[other]))[0],-10)
    def test_other_dynamic_limits_match_recovered_shape(self):
        others=[F.node('sspm',[('alloc-ranges',F.U64(0x40000000)+F.U64(0x60000000))]),F.node('ssmr',[('alloc-range',F.U64(0xc0000000)+F.U64(0x10000000))])]
        rc,o,_=self.plan(tree(extra=others));self.assertEqual(rc,0);self.assertEqual([x.base for x in o.proposed],[0xa0000000,0xa1000000])
    def test_target_changed_owner_and_missing_no_map(self):
        for extra,omit in [([('reg',F.U64(0xa0000000)+F.U64(0x400000))],()),([('status',b'disabled\0')],()),([('reusable',b'')],()),([],('no-map',)),([('alignment',F.U64(0x1000))],('alignment',)),([('compatible',b'other\0')],('compatible',))]:
            targets=[target('consys-reserve-memory',0x400000,extra=extra,omit=omit),target('wifi-reserve-memory',0x300000)]
            self.assertNotEqual(self.plan(tree(targets=targets))[0],0)
    def test_target_and_mblock_duplicates(self):
        ts=[target('consys-reserve-memory',0x400000)]*2+[target('wifi-reserve-memory',0x300000)]
        self.assertNotEqual(self.plan(tree(targets=ts))[0],0)
        self.assertNotEqual(self.plan(tree(memory_extra=[('mblock_info',mblock())]))[0],0)
    def test_fixed_reservation_must_agree_with_lk_ownership(self):
        fixed=F.node('new-owner',[('reg',F.U64(0xa0000000)+F.U64(0x1000))])
        self.assertEqual(self.plan(tree(extra=[fixed]))[0],-9)
        tb=mblock(((0x40000000,0x60000000,0),(0xa0001000,0x11ffff000,1)),((0xa0000000,0x1000,0,'new-owner'),))
        rc,o,_=self.plan(tree(tb,extra=[fixed]),extra=[(0x48000000,0x58000000)])
        self.assertEqual(rc,0);self.assertEqual(o.proposed[0].base,0xa1000000)
    def test_backtracking_and_below_four_gib(self):
        ts=[target('consys-reserve-memory',0x400000,((0xa0000000,0x1400000),)),target('wifi-reserve-memory',0x300000,((0xa0000000,0x300000),))]
        rc,o,_=self.plan(tree(targets=ts));self.assertEqual(rc,0)
        self.assertEqual([x.base for x in o.proposed],[0xa1000000,0xa0000000])
        ts=[target('consys-reserve-memory',0x400000,((0x100000000,0x2000000),)),target('wifi-reserve-memory',0x300000)]
        self.assertEqual(self.plan(tree(targets=ts))[0],-10)
    def test_bounds_and_fresh_revalidation(self):
        b=tree()
        for n in [0,4,39,40,len(b)-1]:self.assertNotEqual(self.plan(b[:n])[0],0)
        self.assertEqual(self.plan(extra=[(0,0)])[0],-6)
        self.assertEqual(self.plan(fdt_pa=0xfffffffffffffff0)[0],-6)
        self.assertEqual(self.plan(extra=[(0x48000000,0x78000000)])[0],-10)
        self.assertEqual(self.plan()[0],0)
    def test_output_and_workspace_canaries(self):
        class Guard(C.Structure):
            _fields_=[('left',C.c_uint64),('value',Ledger),('right',C.c_uint64)]
        class WGuard(C.Structure):
            _fields_=[('left',C.c_uint64),('value',Workspace),('right',C.c_uint64)]
        g=Guard();wg=WGuard();g.left=g.right=wg.left=wg.right=0x123456789abcdef
        r=Request(1,0,1,0x47880000,Range(0x40080000,0x7800000),Range(0xd0000000,0xefe00000),Range(0x40080000,0x100000),None,0)
        b=tree();self.assertEqual(self.lib.cm_plan(C.create_string_buffer(b),len(b),C.byref(r),C.byref(wg.value),C.byref(g.value)),0)
        self.assertEqual([g.left,g.right,wg.left,wg.right],[0x123456789abcdef]*4)
    def test_reserved_owner_change_moves_allocation(self):
        # Same bank/total, but a newly owned16MiB removes the previous first choice.
        tb=mblock(((0x40000000,0x60000000,0),(0xa1000000,0x11f000000,1)),((0xa0000000,0x1000000,0,'new-live-owner'),))
        rc,o,_=self.plan(tree(tb),extra=[(0x48000000,0x58000000)])
        self.assertEqual(rc,0);self.assertEqual([x.base for x in o.proposed],[0xa1000000,0xa2000000])
    def test_capture40_optional_private_input(self):
        name=os.environ.get('CM_CAPTURE40')
        if not name:self.skipTest('set CM_CAPTURE40 to the private captured runtime.dtb')
        b=Path(name).read_bytes();self.assertEqual(hashlib.sha256(b).hexdigest(),'f34de72d965209afeabad918867f32d12fa84ccf910939d7205cb0b205f01ef9')
        rc,o,w=self.plan(b);self.assertEqual(rc,0)
        self.assertEqual([x.base for x in o.proposed],[0xa0000000,0xa1000000])
        self.assertEqual((w.table.free_count,w.table.reserved_count),(18,28))
        self.assertEqual((o.bank_bytes,o.free_bytes,o.lk_reserved_bytes),(6442450944,5711499264,730951680))

if __name__=='__main__':unittest.main()
