#!/usr/bin/env python3
"""Actual C model tests. Optional real profile bytes remain private in the DTB."""
import ctypes as C
from fractions import Fraction
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parent
class Blob(C.Structure):_fields_=[('bytes',C.c_void_p),('length',C.c_size_t)]
class Coeff(C.Structure):_fields_=[('rfg',C.c_uint32),('tune',C.c_uint32),('meter',C.c_uint32)]
class Row(C.Structure):_fields_=[('charge',C.c_uint32),('voltage',C.c_uint32),('resistance',C.c_uint32)]
class Profile(C.Structure):_fields_=[('initialized',C.c_uint32),('rows',(Row*74)*6),('rmin',C.c_uint32),('rmax',C.c_uint32)]
class Sample(C.Structure):_fields_=[('acquired',C.c_uint64),('expires',C.c_uint64),('sequence',C.c_uint64),('ticks',C.c_uint64),('generation',C.c_uint64),('charge',C.c_int64),('current',C.c_int32),('voltage',C.c_uint32),('valid',C.c_uint32)]
class Result(C.Structure):_fields_=[('valid',C.c_uint32),('quality',C.c_uint32),('low',C.c_uint32),('high',C.c_uint32),('ocv_low',C.c_int64),('ocv_high',C.c_int64),('acquired',C.c_uint64),('expires',C.c_uint64),('ocv_acquired',C.c_uint64)]
class State(C.Structure):_fields_=[('phase',C.c_uint32),('fault',C.c_int32),('last_now',C.c_uint64),('previous',Sample),('seed_charge',C.c_int64),('seed_low',C.c_uint32),('seed_high',C.c_uint32),('last',Result)]

def profile_properties(path):
    # Host-only extractor. Input profile admission is performed by C hashes;
    # this convenience extraction is NOT a replacement for a live FDT parser.
    b=Path(path).read_bytes();h=struct.unpack('>10I',b[:40]);assert h[0]==0xd00dfeed and h[1]<=len(b)
    p=h[2];end=p+h[9];stack=[];props={};seen=False
    while p<end:
        token=struct.unpack_from('>I',b,p)[0];p+=4
        if token==1:
            e=b.index(0,p,end);stack.append(b[p:e].decode());p=(e+4)&~3
        elif token==2:stack.pop()
        elif token==3:
            n,o=struct.unpack_from('>II',b,p);p+=8;assert p+n<=end
            name=b[h[3]+o:b.index(0,h[3]+o,h[3]+h[8])].decode();v=b[p:p+n];p=(p+n+3)&~3
            if '/'.join(stack)=='/pwrap@1000d000/main_pmic/mtk_gauge':
                assert name not in props;props[name]=v;seen=True
        elif token==9:break
        else:assert token==4
    assert seen
    return props
class Harness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        so=Path(cls.tmp.name)/'soc.so';subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding','-shared','-fPIC',str(HERE/'battery_soc.c'),str(HERE/'profile_sha256.c'),'-o',str(so)],check=True)
        cls.lib=C.CDLL(str(so));l=cls.lib
        l.bs_sha256.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p]
        l.bs_profile_init.argtypes=[C.POINTER(Profile),C.POINTER(Blob),C.POINTER(C.c_uint32),C.POINTER(C.c_uint32),C.POINTER(C.c_int32),C.POINTER(Coeff)]
        l.bs_ocv_interval.argtypes=[C.POINTER(Profile),C.c_int64,C.c_int64,C.POINTER(Result)]
        l.bs_begin.argtypes=[C.POINTER(State),C.c_uint]
        l.bs_update.argtypes=[C.POINTER(State),C.POINTER(Profile),C.POINTER(Sample),C.c_uint64,C.POINTER(Result)]
        l.bs_read.argtypes=[C.POINTER(State),C.c_uint64,C.POINTER(Result)]
    def init(self,props=None,blobs=None,rows=None,cols=None,temps=None,coeff=None):
        if props:
            blobs=[props[f'battery0_profile_t{i}'] for i in range(6)]
            rows=[struct.unpack('>I',props[f'battery0_profile_t{i}_num'])[0] for i in range(6)] if rows is None else rows
            cols=[struct.unpack('>I',props[f'battery0_profile_t{i}_col'])[0] for i in range(6)] if cols is None else cols
            temps=[struct.unpack('>i',props[f'TEMPERATURE_T{i}'])[0] for i in range(6)] if temps is None else temps
        else:blobs=blobs or [b'\0'*888]*6
        buffers=[C.create_string_buffer(v) for v in blobs];bs=(Blob*6)(*(Blob(C.cast(b,C.c_void_p),len(v)) for b,v in zip(buffers,blobs)))
        p=Profile();C.memset(C.byref(p),0xa5,C.sizeof(p));r=(C.c_uint32*6)(*(rows or [100]*6));c=(C.c_uint32*6)(*(cols or [3]*6));t=(C.c_int32*6)(*(temps or [50,25,10,0,-6,-10]));cf=coeff or Coeff(10,100,75)
        rc=self.lib.bs_profile_init(C.byref(p),bs,r,c,t,C.byref(cf))
        if rc:self.assertEqual(bytes(p),bytes(C.sizeof(p)))
        return rc,p
class Authentication(Harness):
    def test_sha256_boundaries_against_hashlib(self):
        for n in [0,1,3,55,56,63,64,65,127,128,888,4096]:
            b=bytes(i%251 for i in range(n));out=C.create_string_buffer(32);self.lib.bs_sha256(C.create_string_buffer(b),len(b),out);self.assertEqual(out.raw,hashlib.sha256(b).digest())
    def test_unverified_and_truncated_profiles_fail(self):
        for b in [b'',bytes(887),bytes(888),bytes(889)]:self.assertEqual(self.init(blobs=[b]*6)[0],-2)
    def test_uninitialized_ocv_and_default_off(self):
        r=Result();p=Profile();s=State();self.assertEqual(self.lib.bs_ocv_interval(C.byref(p),3800000,3800000,C.byref(r)),-2)
        self.assertEqual(self.lib.bs_begin(C.byref(s),0),-3);self.assertEqual(self.lib.bs_read(C.byref(s),0,C.byref(r)),-3);self.assertEqual(bytes(r),bytes(C.sizeof(r)))

class RealProfile(Harness):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('BS_PROFILE_DTB')
        if not path:raise unittest.SkipTest('set BS_PROFILE_DTB to the private stock/captured DTB for real-profile model tests')
        super().setUpClass();cls.props=profile_properties(path)
    def setUp(self):
        rc,self.p=self.init(self.props);self.assertEqual(rc,0);self.s=State();self.assertEqual(self.lib.bs_begin(C.byref(self.s),1),0)
    def sample(self,i=1,**kw):
        v=Sample(i*1000000,i*1000000+2000000,i,2*i,1,0,0,3900000,7)
        for k,val in kw.items():setattr(v,k,val)
        return v
    def update(self,v,now=None):
        r=Result();C.memset(C.byref(r),0xa5,C.sizeof(r));rc=self.lib.bs_update(C.byref(self.s),C.byref(self.p),C.byref(v),v.acquired+100 if now is None else now,C.byref(r))
        if rc:self.assertEqual(bytes(r),bytes(C.sizeof(r)))
        return rc,r
    def seed(self,**kw):
        self.assertEqual(self.update(self.sample(1,**kw))[0],1);rc,r=self.update(self.sample(2,**kw));self.assertEqual(rc,0);self.assertEqual(r.valid,1);return r
    def lookup(self,lo,hi=None):
        r=Result();rc=self.lib.bs_ocv_interval(C.byref(self.p),lo,lo if hi is None else hi,C.byref(r));return rc,r
    def test_exact_profiles_and_metadata_mutations(self):
        self.assertEqual((self.p.rmin,self.p.rmax),(740,990))
        for key in ['battery0_profile_t0','battery0_profile_t5']:
            props=dict(self.props);x=bytearray(props[key]);x[321]^=1;props[key]=bytes(x);self.assertEqual(self.init(props)[0],-2)
        for kw in [{'rows':[74]*6},{'cols':[4]*6},{'temps':[50,25,10,0,-10,-25]},{'coeff':Coeff(11,100,75)},{'coeff':Coeff(10,101,75)},{'coeff':Coeff(10,100,100)}]:self.assertEqual(self.init(self.props,**kw)[0],-2)
    def test_temperature_and_nonmonotonic_ambiguity_interval(self):
        rc,r=self.lookup(4070000);self.assertEqual(rc,0);self.assertEqual(r.valid,0);self.assertLess(r.low,8600);self.assertGreater(r.high,8650)
        rc,r=self.lookup(3704700,3714600);self.assertEqual(rc,0);self.assertLessEqual(r.low,2354);self.assertGreaterEqual(r.high,2591)
    def test_ocv_grid_contains_every_exact_segment_intersection(self):
        # Independent rational oracle: no integer truncation copied from C.
        rows=[[tuple(getattr(x,k) for k in ('charge','voltage','resistance')) for x in ts] for ts in self.p.rows]
        for voltage in range(3410000,4380001,10000):
            rc,r=self.lookup(voltage);self.assertEqual(rc,0);values=[]
            for table in rows:
                for a,b in zip(table,table[1:]):
                    va,vb=a[1]*100,b[1]*100
                    if min(va,vb)<=voltage<=max(va,vb) and va!=vb:
                        q=Fraction(a[0]*100)+Fraction((b[0]-a[0])*100*(voltage-va),vb-va)
                        values.append((2200000-q)*10000/2200000)
            self.assertTrue(values);self.assertLessEqual(r.low,min(values));self.assertGreaterEqual(r.high,max(values))
    def test_no_value_before_two_forward_fresh_samples(self):
        self.assertEqual(self.update(self.sample())[0],1);r=Result();self.assertEqual(self.lib.bs_read(C.byref(self.s),1100000,C.byref(r)),1);self.assertEqual(r.valid,0)
        rc,r=self.update(self.sample(2));self.assertEqual(rc,0);self.assertEqual(r.quality,63)
    def test_ir_sign_and_current_resistance_envelope(self):
        r=self.seed(current=1000000);self.assertLess(r.ocv_high,3900000)
        self.assertEqual((r.ocv_low,r.ocv_high),(3782500,3809500))
        self.lib.bs_begin(C.byref(self.s),1);r=self.seed(current=-1000000);self.assertGreater(r.ocv_low,3900000)
        self.assertEqual((r.ocv_low,r.ocv_high),(3990500,4017500))
    def test_car_integration_ignores_new_voltage_not_reseeded(self):
        seed=self.seed(current=-360000)
        for i in range(3,1003):
            rc,r=self.update(self.sample(i,current=-360000,charge=-(i-2)*100,voltage=3705000 if i%2 else 4350000));self.assertEqual(rc,0)
        self.assertEqual(r.ocv_acquired,2000000);self.assertEqual(r.acquired,1002000000)
        self.assertLess(r.high,seed.high-450);self.assertGreater(r.low,seed.low-460)
    def test_charge_direction_and_reversal_with_consistent_delta(self):
        seed=self.seed(current=360000)
        rc,r=self.update(self.sample(3,current=360000,charge=100));self.assertEqual(rc,0);self.assertGreaterEqual(r.high,seed.high)
        rc,r=self.update(self.sample(4,current=-360000,charge=0));self.assertEqual(rc,0)
    def test_wrong_sign_large_delta_latches_invalid(self):
        self.seed(current=-1000000);self.assertEqual(self.update(self.sample(3,current=-1000000,charge=300))[0],-8)
        self.assertEqual(self.update(self.sample(4))[0],-10)
    def test_jump_and_counter_origin_reset_not_reseeded(self):
        self.seed(charge=1000000);self.assertEqual(self.update(self.sample(3,charge=0))[0],-7)
        self.assertEqual(self.update(self.sample(4,charge=1000000))[0],-10)
    def test_timestamp_sequence_generation_and_nter_guards(self):
        cases=[dict(acquired=2000000),dict(sequence=2),dict(generation=2),dict(ticks=4),dict(ticks=3),dict(ticks=1<<33),dict(acquired=8000000,expires=10000000)]
        for kw in cases:
            with self.subTest(kw=kw):
                self.lib.bs_begin(C.byref(self.s),1);self.seed();self.assertLess(self.update(self.sample(3,**kw))[0],0)
    def test_stale_partial_future_and_unit_errors(self):
        for kw in [dict(valid=3),dict(valid=15),dict(expires=1000000),dict(expires=3000001),dict(charge=1),dict(charge=-(1<<63)),dict(current=1),dict(current=2000100),dict(voltage=3900001),dict(voltage=0)]:
            self.lib.bs_begin(C.byref(self.s),1);self.assertLess(self.update(self.sample(1,**kw))[0],0)
        self.lib.bs_begin(C.byref(self.s),1);self.assertEqual(self.update(self.sample(),now=999999)[0],-4)
    def test_expiry_and_clock_reversal_even_without_updates(self):
        seed=self.seed();r=Result();self.assertEqual(self.lib.bs_read(C.byref(self.s),seed.expires,C.byref(r)),-4);self.assertEqual(r.valid,0)
        self.lib.bs_begin(C.byref(self.s),1);self.seed();self.assertEqual(self.lib.bs_read(C.byref(self.s),3000000,C.byref(r)),0)
        self.assertEqual(self.lib.bs_read(C.byref(self.s),2999999,C.byref(r)),-5)
    def test_model_boundary_is_invalidated_not_silently_clamped(self):
        self.seed(voltage=3000000);self.assertEqual(self.update(self.sample(3,voltage=3000000,charge=-100))[0],-9)
    def test_no_fixed_car_origin_assumption(self):
        a=self.seed(charge=-8000000);self.lib.bs_begin(C.byref(self.s),1);b=self.seed(charge=8000000)
        self.assertEqual((a.low,a.high),(b.low,b.high))
    def test_car_quantization_jump_boundary(self):
        for delta,expected in [(700,0),(800,-7)]:
            self.lib.bs_begin(C.byref(self.s),1);self.seed(current=1000000)
            self.assertEqual(self.update(self.sample(3,current=1000000,charge=delta))[0],expected)
    def test_forward_nter_wrap_matches_native_half_range_rule(self):
        self.assertEqual(self.update(self.sample(1,ticks=(1<<33)-2))[0],1)
        self.assertEqual(self.update(self.sample(2,ticks=0))[0],0)
        self.assertEqual(self.update(self.sample(3,ticks=1<<32))[0],-6)
    def test_update_cannot_reverse_clock_after_successful_read(self):
        self.seed();r=Result();self.assertEqual(self.lib.bs_read(C.byref(self.s),3500000,C.byref(r)),0)
        self.assertEqual(self.update(self.sample(3),now=3100000)[0],-5)
    def test_fresh_input_not_extended_by_late_call(self):
        self.assertEqual(self.update(self.sample(1),now=2999999)[0],1)
        self.assertEqual(self.update(self.sample(2),now=3999999)[0],0)
        r=Result();self.assertEqual(self.lib.bs_read(C.byref(self.s),4000000,C.byref(r)),-4)

if __name__=='__main__':unittest.main()
