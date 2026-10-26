"""Execute native initialization/transfer admission with fake MMIO and clocks.

Compile only a small host harness containing the actual platform functions;
never build a kernel/payload or connect a device.
"""
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
PHYSICAL=HERE.parents[1]/'physical'
sys.path.insert(0,str(PHYSICAL))
import build_payload


def function(source,name):
    """Extract a complete named definition, retaining the original C body."""
    marker=source.index(name+'(')
    # charger_entry_check is separately stubbed; selected functions have no
    # forward declarations. Count braces from the complete definition.
    begin=source.rfind('\n',0,marker)+1
    opening=source.index('{',marker)
    depth=1;end=opening+1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[begin:end]+'\n'


HARNESS=r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mtk_i2c_v2.h"
#include "native_setup.h"
#include "mt6762_charger_entry.h"
#include "mt6762_charger_setup.h"
#include "../../../../bsd/dev/mt6762_charger_protocol.h"
typedef uintptr_t vm_offset_t;
typedef uint32_t ppnum_t;
#define PAGE_SIZE 16384
#define PAGE_SHIFT 14
#define PAGE_MASK 16383
#define KMA_KOBJECT 1
#define KMA_ZERO 2
#define KMA_DATA 4
#define VM_KERN_MEMORY_IOKIT 0
#define KERN_SUCCESS 0
static uintptr_t top=0x10000000,infra=0x10001000,gic=0x0c000000,kernel_map;
static uint32_t parent_index=2,parent_hz=124800000,requested_hz=100000;
static int ready=1,mt6762_i2c_lock,charger_entry_admitted;
static unsigned grant0,grant5,inherited,setup_only,touch,entry_ok,entry_calls;
static unsigned readonly_probe,pwrap_probe,charger_verified,charger_owned,pwrap_owned;
static unsigned physical_readback,shared_clocks=1,late_gate,infra4;
static unsigned writes,engine_calls,ready_logs,setup_logs,strict_result;
static unsigned admitted_logs,read_logs,flip_offset,flip_mask,fail_index;
static int fail_result;
static uint8_t charger_id=0xf0;
static uint16_t registers[2][64];
static unsigned char allocation[PAGE_SIZE];
static int flag(const char *name) {
    if(!strcmp(name,"i2c0-verified"))return grant0;
    if(!strcmp(name,"i2c5-verified"))return grant5;
    if(!strcmp(name,"charger-inherited-probe"))return inherited;
    if(!strcmp(name,"charger-setup-only"))return setup_only;
    if(!strcmp(name,"touch-inherited-probe"))return touch;
    if(!strcmp(name,"charger-readonly-probe"))return readonly_probe;
    if(!strcmp(name,"pwrap-inherited-probe"))return pwrap_probe;
    if(!strcmp(name,"charger-verified"))return charger_verified;
    if(!strcmp(name,"charger-control-owned"))return charger_owned;
    if(!strcmp(name,"pwrap-write-owned"))return pwrap_owned;
    assert(!"unexpected flag");return 0;
}
static int mocklog(const char *fmt,...) {
    char output[512];va_list ap;va_start(ap,fmt);
    int n=vsnprintf(output,sizeof(output),fmt,ap);va_end(ap);
    if(strstr(output,"MT6762_I2C_READY"))ready_logs++;
    if(strstr(output,"MT6762_PSC_READONLY_ADMITTED transactions=6"))admitted_logs++;
    if(strstr(output,"MT6762_I2C_PSC_READ index="))read_logs++;
    if(strstr(output,"MT6762_I2C_SETUP_ONLY")) {
        setup_logs++;strict_result=strstr(output,"strict=1")!=NULL;
    }
    return n;
}
#define kprintf mocklog
#define printf mocklog
static int clocks_stable(void) {return shared_clocks;}
static int charger_entry_check(void) {entry_calls++;return entry_ok;}
static unsigned pin_mode(unsigned pin) {(void)pin;return 1;}
static int mt6762_handoff_u32(const char *name,uint32_t *value) {
    assert(!strcmp(name,"i2c0-hz") || !strcmp(name,"i2c5-hz"));*value=requested_hz;return 0;
}
static void *mt6762_map_mmio(uint64_t address,size_t length) {
    assert(length==0x1000 || length==0x80);return (void *)(uintptr_t)address;
}
static uint32_t r32(uintptr_t base,unsigned offset) {
    if(base==infra && offset==0xc8)return infra4;
    if(base==top && offset==0xa0)return 0x1030202;
    return 0;
}
static void w32(uintptr_t base,unsigned offset,uint32_t value) {
    assert(base==gic && (offset==0x18c || offset==0x194));
    assert(value==(1u<<20) || value==4);writes++;
}
static void barrier(void *p) {(void)p;}
static void wait_us(void *p,unsigned us) {(void)p;(void)us;}
static int kmem_alloc_contig(uintptr_t map,vm_offset_t *memory,size_t size,
    unsigned align,ppnum_t maximum,unsigned zero,unsigned flags,unsigned tag) {
    (void)map;(void)align;(void)zero;(void)flags;(void)tag;
    assert(size==PAGE_SIZE && maximum==0x3ffff);*memory=(uintptr_t)allocation;return 0;
}
static void kmem_free(uintptr_t map,vm_offset_t memory,size_t size) {(void)map;(void)memory;(void)size;}
static uint64_t kvtophys(vm_offset_t memory) {assert(memory==(uintptr_t)allocation);return 0x70000000;}
static void dma_to_device(void *p,size_t tx,size_t rx) {(void)p;(void)tx;(void)rx;assert(0);}
static void dma_to_cpu(void *p,size_t rx) {(void)p;(void)rx;assert(0);}
static void lck_mtx_lock(int *l) {(void)l;}
static void lck_mtx_unlock(int *l) {(void)l;}
'''

CALLBACKS=r'''
static uint16_t br16(void *context,unsigned offset) {
    struct native_bus *b=context;unsigned n=b->id==5;
    uint16_t value=registers[n][offset/2];
    if(physical_readback && offset==0x48)value&=0xff;
    if(physical_readback && offset==0x30)value|=0x8000;
    if(flip_mask && offset==flip_offset)value^=flip_mask;
    return value;
}
static void bw16(void *context,unsigned offset,uint16_t value) {
    struct native_bus *b=context;
    assert(offset!=0 && offset!=4 && offset!=0x24); /* no data/address/START */
    writes++;registers[b->id==5][offset/2]=value;
    if(late_gate && offset==0x4c)infra4=1u<<19;
}
static uint32_t dr32(void *p,unsigned offset) {(void)p;assert(offset==8);return 0;}
static void dw32(void *p,unsigned offset,uint32_t value) {(void)p;(void)offset;(void)value;assert(0);}
int mtk_i2c_v2_transfer(struct mtk_i2c_v2 *b,struct mtk_i2c_msg *m,size_t n) {
    struct native_bus *bus=b->context;engine_calls++;
    if(bus->charger_readonly) {
        assert(n==2 && m[0].address==0x6a && m[1].address==0x6a);
        assert(!m[0].read && m[1].read && m[0].length==1 && m[1].length==1);
        if(engine_calls==fail_index)return fail_result;
        m[1].data[0]=m[0].data[0]==3?charger_id:m[0].data[0]==1?0xfc:0x10;
    }
    return (int)n;
}
'''

CASES=r'''
static void reset(void) {
    memset(buses,0,sizeof(buses));memset(registers,0,sizeof(registers));
    grant0=grant5=inherited=setup_only=touch=0;
    readonly_probe=charger_verified=charger_owned=pwrap_owned=0;pwrap_probe=1;
    charger_entry_admitted=entry_ok=shared_clocks=1;
    writes=engine_calls=ready_logs=setup_logs=strict_result=entry_calls=0;
    physical_readback=infra4=late_gate=0;
    admitted_logs=read_logs=flip_offset=flip_mask=fail_index=0;fail_result=-4;
    parent_index=2;parent_hz=124800000;requested_hz=100000;charger_id=0xf0;
}
static int transfer(unsigned id) {unsigned char reg=3,value=0;return mt6762_i2c_transfer(id,0x6a,&reg,1,&value,1);}
static int read_psc(void *unused,uint8_t reg,uint8_t *value) {
    (void)unused;return mt6762_i2c_transfer(5,0x6a,&reg,1,value,1);
}
static void readonly_setup(void) {
    reset();grant5=inherited=readonly_probe=physical_readback=1;
    initialize_bus(&buses[1],5);assert(mt6762_i2c_ready(5) && admitted_logs==1);
}
int main(void) {
    /* Default laboratory bus5 behavior remains unchanged, including the
     * lack of a physical I2C5 entry claim in that existing synthetic path. */
    reset();grant5=1;infra4=7u<<18;initialize_bus(&buses[1],5);
    assert(mt6762_i2c_ready(5) && ready_logs==1 && !entry_calls);
    assert(!transfer(5) && engine_calls==1);
    /* The independently measured bus5 profile matches only physical31;
     * setup-only stays blocked even with both observation modes requested. */
    for(unsigned physical=0;physical<2;physical++) {
        reset();grant5=inherited=setup_only=1;physical_readback=physical;
        initialize_bus(&buses[1],5);
        assert(writes && setup_logs==1 && strict_result==physical && !ready_logs && !admitted_logs);
        assert(buses[1].setup_only && !buses[1].engine.initialized && buses[1].engine.faulted);
        assert(!mt6762_i2c_ready(5) && transfer(5)==-1 && !engine_calls);
        buses[1].engine.initialized=1;buses[1].engine.faulted=0;
        assert(!mt6762_i2c_ready(5) && transfer(5)==-1 && !engine_calls);
    }
    reset();grant5=inherited=setup_only=readonly_probe=physical_readback=1;
    initialize_bus(&buses[1],5);
    assert(setup_logs==1 && strict_result && !admitted_logs && transfer(5)==-1 && !engine_calls);
    /* A missing entry grant, prior refusal, or fresh refusal permits no write. */
    for(unsigned which=0;which<3;which++) {
        reset();grant5=setup_only=1;inherited=which!=0;
        charger_entry_admitted=which==2;entry_ok=which!=2;
        initialize_bus(&buses[1],5);assert(!writes && !mt6762_i2c_ready(5));
    }
    for(unsigned bit=18;bit<=20;bit++) {
        reset();grant5=inherited=setup_only=1;infra4=1u<<bit;
        initialize_bus(&buses[1],5);assert(!writes && !mt6762_i2c_ready(5));
    }
    reset();grant5=inherited=setup_only=late_gate=1;initialize_bus(&buses[1],5);
    assert(setup_logs==1 && !strict_result && !ready_logs && transfer(5)==-1);
    /* Inherited entry alone is never a general bus5 transaction grant. */
    reset();grant5=inherited=1;initialize_bus(&buses[1],5);
    assert(!writes && !mt6762_i2c_ready(5));
    for(unsigned missing=0;missing<6;missing++) {
        reset();grant5=inherited=readonly_probe=physical_readback=1;
        if(missing==0)inherited=0;
        if(missing==1)pwrap_probe=0;
        if(missing==2)charger_verified=1;
        if(missing==3)charger_owned=1;
        if(missing==4)pwrap_owned=1;
        if(missing==5)charger_entry_admitted=0;
        initialize_bus(&buses[1],5);assert(!writes && !mt6762_i2c_ready(5) && !admitted_logs);
    }
    /* Reject every single-bit corruption of all eight post-write fields. */
    const unsigned offsets[]={0x48,0x20,0x2c,0x30,0x34,0x28,0x1c,0x4c};
    for(unsigned field=0;field<8;field++)for(unsigned bit=0;bit<16;bit++) {
        reset();grant5=inherited=readonly_probe=physical_readback=1;
        flip_offset=offsets[field];flip_mask=1u<<bit;initialize_bus(&buses[1],5);
        assert(!mt6762_i2c_ready(5) && !admitted_logs && !engine_calls);
    }
    reset();grant5=inherited=readonly_probe=1;initialize_bus(&buses[1],5);
    assert(!mt6762_i2c_ready(5) && !admitted_logs); /* Generic404/HS0 is not capture31. */
    for(unsigned wrong=0;wrong<3;wrong++) {
        reset();grant5=inherited=readonly_probe=physical_readback=1;
        if(wrong==0)parent_index=1;
        if(wrong==1)parent_hz=26000000;
        if(wrong==2)requested_hz=400000;
        initialize_bus(&buses[1],5);assert(!mt6762_i2c_ready(5) && !admitted_logs);
    }
    /* Every dedicated gate is checked on later transfers; a cleared ADT flag
     * cannot remove the restriction already latched in the private bus. */
    for(unsigned bit=18;bit<=20;bit++) {
        readonly_setup();inherited=0;infra4=1u<<bit;
        assert(transfer(5)==-1 && !engine_calls && buses[1].engine.faulted);
    }
    const struct mt6762_psc_io io={NULL,read_psc,NULL};
    struct mt6762_psc_observation value={0};
    readonly_setup();unsigned setup_writes=writes;
    uint8_t command[]={1,4},byte=0;
    assert(mt6762_i2c_transfer(5,0x6a,command,2,NULL,0)==-1);
    assert(mt6762_i2c_transfer(5,0x3e,command,2,NULL,0)==-1);
    assert(mt6762_i2c_transfer(5,0x6a,NULL,0,&byte,1)==-1);
    assert(mt6762_i2c_transfer(5,0x6a,command,1,&byte,1)==-1); /* Expected ID first. */
    assert(!engine_calls && !buses[1].charger_reads && writes==setup_writes);
    for(unsigned pass=0;pass<2;pass++) {
        assert(!mt6762_psc_observe(&io,&value));
        assert(value.id==0xf0 && value.control==0xfc && value.status==0x10);
    }
    assert(engine_calls==6 && read_logs==6 && buses[1].charger_reads==6 && !mt6762_i2c_ready(5));
    assert(transfer(5)==-1 && engine_calls==6 && writes==setup_writes);
    /* Wrong identity stops before control/status; log still retains the ID. */
    readonly_setup();charger_id=0xee;value=(struct mt6762_psc_observation){1,2,3};
    assert(mt6762_psc_observe(&io,&value)==-2 && engine_calls==1 && read_logs==1);
    assert(value.id==1 && value.control==2 && value.status==3);
    /* Any failed/short/excess transfer consumes its attempt and latches fault;
     * no ambiguous read can be automatically retried by the caller. */
    for(unsigned failure=1;failure<=6;failure++)for(int result=-4;result<=3;result++) {
        if(result==2)continue;
        readonly_setup();fail_index=failure;fail_result=result;
        for(unsigned pass=0;pass<2;pass++)if(mt6762_psc_observe(&io,&value))break;
        assert(engine_calls==failure && read_logs==failure && buses[1].charger_reads==failure);
        assert(buses[1].engine.faulted && !mt6762_i2c_ready(5));
        assert(transfer(5)==-1 && engine_calls==failure);
    }
    /* The bus5 setup flag must not suppress the existing physical touch bus. */
    reset();grant0=touch=physical_readback=inherited=setup_only=1;infra4=7u<<18;
    initialize_bus(&buses[0],0);
    assert(mt6762_i2c_ready(0) && ready_logs==1 && !entry_calls && !setup_logs);
    assert(!transfer(0) && engine_calls==1);
    puts("PASS: capture31 setup, six restricted PSC reads, setup-only/fault/mode/gate isolation; bus0 preserved");
    return 0;
}
'''


class ChargerSetupTests(unittest.TestCase):
    def test_real_native_setup_and_transaction_admission(self):
        source=(ROOT/'bsd/dev/mt6762_platform.c').read_text()
        bus=source[source.index('struct native_bus {'):source.index('static struct native_bus buses[2];')]
        # Timing is the actual canonical code, while the transfer function is
        # replaced by a counter so any wrongly admitted transaction is visible.
        timing=(ROOT/'bsd/dev/mt6762_i2c.c').read_text().split('/* Controller accesses')[0]
        timing=timing.replace('#include "../sys/mt6762_i2c.h"','')
        functions=''.join(function(source,n) for n in
            ['bus_clocks_stable','initialize_bus','mt6762_i2c_ready','mt6762_i2c_transfer'])
        code=HARNESS+bus+'static struct native_bus buses[2];\n'+CALLBACKS+timing+functions+CASES
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(code)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),'-I'+str(HERE.parent/'i2c'),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True,timeout=10)

    def test_producer_properties_are_ungranted_and_setup_only(self):
        props=build_payload.charger_setup_properties()
        self.assertEqual(set(build_payload.CHARGER_SETUP_FLAGS),
            {'dma-direct','i2c-pads-verified','i2c5-verified','charger-inherited-probe','charger-setup-only'})
        for name in build_payload.CHARGER_SETUP_FLAGS:self.assertEqual(props[name],bytes(4))
        for name,value in {'i2c-parent-index':2,'i2c-parent-hz':124800000,'i2c5-hz':100000}.items():
            self.assertEqual(props[name],struct.pack('<I',value))
        for name in ['charger-readonly-probe','charger-verified','charger-control-owned',
                     'pwrap-write-owned','touch-inherited-probe','i2c0-verified']:
            self.assertNotIn(name,props)
        tree={'name':'device-tree','props':{},'children':[
            {'name':'chosen','props':{},'children':[
                {'name':'mt6762-handoff','props':props,'children':[]}]}]}
        raw=build_payload.encode_adt(tree);decoded,end,positions=build_payload.decode_adt(raw)
        self.assertEqual(end,len(raw))
        self.assertEqual(decoded['children'][0]['children'][0]['props'],props)
        for name in build_payload.CHARGER_SETUP_FLAGS:
            offset=positions['/device-tree/chosen/mt6762-handoff/'+name]
            self.assertEqual(raw[offset:offset+4],bytes(4))

    def test_cli_rejects_missing_physical_preconditions_before_file_access(self):
        base=[sys.executable,str(PHYSICAL/'build_payload.py'),'--kernel','/missing/kernel',
              '--template','/missing/template','--llvm','/missing/llvm','--out','/missing/output',
              '--diagnostic','/missing/pid1','--native-charger-setup-probe']
        for extra,reason in [([],b'charger setup requires'),
            (['--native-pwrap-probe'],b'requires native display and passive'),
            (['--native-pwrap-probe','--native-display'],b'requires native display and passive')]:
            result=subprocess.run(base+extra,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,2);self.assertIn(reason,result.stderr)
            self.assertNotIn(b'FileNotFoundError',result.stderr)

    def test_setup_option_refuses_a_kernel_without_transaction_blocking(self):
        build_payload.require_charger_setup_kernel(b'old-kernel',False)
        with self.assertRaisesRegex(ValueError,'transaction blocking'):
            build_payload.require_charger_setup_kernel(b'old-kernel',True)
        build_payload.require_charger_setup_kernel(
            b'prefix\0MT6762_I2C_SETUP_ONLY bus=%u strict=%u transactions=0\n\0suffix',True)

    def test_kernel_dependency_identity_includes_shared_entry_header(self):
        path=HERE.parents[1]/'source_snapshot.py'
        spec=importlib.util.spec_from_file_location('charger_source_snapshot',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        report=module.snapshot(ROOT)
        for header in ['mt6762_charger_entry.h','mt6762_charger_setup.h']:
            name='tools/mt6762/hardware/power/'+header
            self.assertEqual(report['files'][name],hashlib.sha256((ROOT/name).read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
