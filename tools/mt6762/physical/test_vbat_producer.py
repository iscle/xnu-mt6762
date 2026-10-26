"""Exercise live FDT/PMIC admission, expiry and clear-by-default packaging."""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import build_payload as build

HERE=Path(__file__).resolve().parent
POWER=HERE.parent/'hardware/power'
sys.path.insert(0,str(POWER))
from test_vbat_profile import tree,fdt

WRAPPER=r'''
#include "native_vbat.h"
struct state {unsigned reads,ticks,fail,change,late,reverse,frozen;};
static int rd(void *context,uint16_t reg,uint16_t *value)
{
    struct state *s=context;
    unsigned i=s->reads++%MT6762_VBAT_ENTRY_COUNT;
    if(reg!=mt6762_vbat_entry_regs[i])return -2;
    if(s->reads==s->fail)return -1;
    static const uint16_t extra[]={0x80aa,0x100,0x100,0x8000,0x8000};
    *value=i<MT6762_VBAT_FIXED_COUNT?mt6762_vbat_fixed_values[i]:extra[i-MT6762_VBAT_FIXED_COUNT];
    if(s->reads==s->change)*value^=1;
    if(s->change==49 && reg==0x114c)*value|=0x100;
    if(s->change==50 && reg==0x114c)*value|=0x400;
    return 0;
}
static uint64_t tick(void *context)
{
    struct state *s=context;s->ticks++;
    if(s->frozen)return 100;
    if(s->ticks==s->reverse)return 0;
    if(s->ticks==s->late)return MT6762_VBAT_ADMISSION_TICKS+200;
    return 100+s->ticks;
}
int run(const void *blob,size_t size,unsigned fail,unsigned change,unsigned late,
    unsigned reverse,unsigned frozen,uint32_t *values,unsigned *counts)
{
    struct state s={0,0,fail,change,late,reverse,frozen};
    const struct mt6762_vbat_entry_io io={&s,rd,tick};
    struct mt6762_vbat_entry_report report;
    int ok=mt6762_vbat_admit(blob,size,&io,values,&report);
    counts[0]=s.reads;counts[1]=s.ticks;counts[2]=report.status;
    counts[3]=report.reads;counts[4]=report.reuse_word;counts[5]=report.reuse_passes;
    return ok;
}
'''

class VoltageProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        directory=Path(cls.tmp.name);(directory/'test.c').write_text(WRAPPER)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',
            '-I',str(HERE),str(directory/'test.c'),str(POWER/'mt6762_vbat_fdt.c'),
            '-o',str(directory/'test.so')],check=True)
        cls.lib=C.CDLL(str(directory/'test.so'))
        cls.lib.run.argtypes=[C.c_void_p,C.c_size_t,*([C.c_uint]*5),
            C.POINTER(C.c_uint32),C.POINTER(C.c_uint)]
        cls.lib.run.restype=C.c_int

    def run_admit(self,blob=None,fail=0,change=0,late=0,reverse=0,frozen=0):
        if blob is None:blob=fdt(tree()[0])
        raw=C.create_string_buffer(blob);values=(C.c_uint32*6)(*[0xa5a5a5a5]*6)
        counts=(C.c_uint*6)()
        ok=self.lib.run(raw,len(blob),fail,change,late,reverse,frozen,values,counts)
        if not ok:self.assertEqual(list(values),[0]*6)
        return ok,list(values),list(counts)

    def test_two_passes_preserve_whole_live_words(self):
        ok,values,counts=self.run_admit()
        self.assertEqual((ok,values,counts),
            (1,[1,0x80aa,0x100,0x100,0x8000,0x8000],[48,97,1,48,0x8000,3]))

    def test_every_transport_fault_and_profile_change(self):
        for index in range(1,49):
            with self.subTest(index=index):
                ok,_,counts=self.run_admit(fail=index)
                self.assertFalse(ok);self.assertEqual(counts[0],index)
                self.assertFalse(self.run_admit(change=index)[0])

    def test_deadline_includes_last_read_and_timer_regression(self):
        for index in range(2,98):
            self.assertFalse(self.run_admit(late=index)[0])
            self.assertFalse(self.run_admit(reverse=index)[0])
        self.assertFalse(self.run_admit(frozen=1)[0])

    def test_invalid_fdt_has_no_bus_access(self):
        for blob in (b'',bytes(40),fdt(tree()[0])[:-1]):
            ok,_,counts=self.run_admit(blob)
            self.assertFalse(ok);self.assertEqual(counts[:2],[0,0])
            self.assertEqual(counts[2:], [2,0,0,0])

    def test_reuse_refusal_preserves_observation_without_grant(self):
        for change,word in ((49,0x8100),(50,0x8400)):
            ok,values,counts=self.run_admit(change=change)
            self.assertFalse(ok);self.assertEqual(values,[0]*6)
            self.assertEqual(counts,[24,49,5,24,word,1])

    def test_voltage_properties_start_clear_without_broad_grants(self):
        for gauge in (False,True):
            props=build.battery_observer_properties(gauge,vbat=True)
            for key in ('vbat-inherited-observer',*build.VBAT_OBSERVER_VALUES,
                        *build.VBAT_OBSERVER_DIAGNOSTICS):
                self.assertEqual(props[key],bytes(4))
            for key in ('adc-verified','pwrap-write-owned','charger-control-owned','fgauge-owned'):
                self.assertNotIn(key,props)
            raw=build.encode_adt({'name':'device-tree','props':props,'children':[]})
            decoded,end,_=build.decode_adt(raw)
            self.assertEqual((decoded['props'],end),(props,len(raw)))

    def test_missing_consumer_and_dependency_rejected(self):
        with self.assertRaisesRegex(ValueError,'voltage observer requires'):
            build.require_battery_observer_kernel(b'',False,False,True)
        build.require_battery_observer_kernel(
            b'MT6762_VBAT_OBSERVER_READY channel=1 max_requests_per_sample=1\n\0',False,False,True)
        result=subprocess.run([sys.executable,str(HERE/'build_payload.py'),
            '--kernel','/absent/kernel','--template','/absent/template','--llvm','/absent/llvm',
            '--out','/absent/out','--diagnostic','/absent/pid1','--native-vbat-observer'],
            capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertIn(b'voltage observer requires',result.stderr)
        self.assertNotIn(b'FileNotFoundError',result.stderr)

if __name__=='__main__':unittest.main()
