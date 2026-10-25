/* Compile the actual included native BIF consumer with controlled PMIC/time. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../../../../bsd/dev/mt6762_bif_protocol.h"
#define MT6762_BIF_HOST_TEST 1
#define NSEC_PER_MSEC 1000000
static int adc_mutex,adc_ready=1;
static uint64_t now,read_delay,interval_delay,lock_wait,duration;
static unsigned operations,reads,writes,fail_at,requested,ready_reads;
static uint16_t drift_reg;
static unsigned drift_after_request,missed_generation;
static const uint16_t registers[]={8,0xa,0x1236,0x10de,0x10e0,0x1120,0x1126,
    0x1128,0x112e,0x1132,0x1136,0x113a,0x113c,0x1008,
    0x11a2,0x11a4,0x11a6,0x11a8,0x11aa,0x11ac};
static const uint16_t words[]={0x5730,0x101,4,0x4000,0,0,0,0,0,0,0,0,0,
    0x1357,0x2468,0x369c,0x48ad,0x5bce,0x6df0,0x7e12};
static void lck_mtx_lock(int *m){assert(!*m);*m=1;now+=lock_wait;lock_wait=0;}
static void lck_mtx_unlock(int *m){assert(*m);*m=0;}
static void clock_get_uptime(uint64_t *t){*t=now;}
static void clock_interval_to_absolutetime_interval(unsigned ms,unsigned scale,uint64_t *t)
{assert(ms==2000 && scale==NSEC_PER_MSEC);now+=interval_delay;*t=duration;}
static int mt6762_pwrap_read16(uint16_t reg,uint16_t *value)
{
    operations++;reads++;now+=read_delay;
    if(operations==fail_at)return -EIO;
    if(reg==0x108e || reg==0x109e) {
        assert(requested==(reg==0x108e?8u:2048u));
        *value=(!ready_reads++ && !missed_generation)?0:
            (uint16_t)(0x8000|(reg==0x108e?1400:4089));return 0;
    }
    for(unsigned i=0;i<20;i++)if(reg==registers[i]) {
        *value=words[i];
        if(reg==drift_reg && (!drift_after_request || requested==2048))*value^=1;
        return 0;
    }
    assert(!"read outside enumerated state/ADC set");return -EIO;
}
static int adc_rd(void *context,uint16_t reg,uint16_t *value)
{(void)context;return mt6762_pwrap_read16(reg,value);}
static int adc_wr(void *context,uint16_t reg,uint16_t value)
{
    (void)context;operations++;writes++;
    assert(reg==0x110e && (value==8 || value==2048));
    if(operations==fail_at)return -EIO;
    requested=value;ready_reads=0;return 0;
}
static void pwrap_delay(void *context,unsigned us){(void)context;now+=us;}
static int verified(const char *name){(void)name;return 1;}
static int mt6762_handoff_u32(const char *name,uint32_t *value)
{
    if(!strcmp(name,"bif-tdet"))*value=4;
    else if(!strcmp(name,"bif-sw-gain-trim"))*value=0x4000;
    else *value=0;
    return 0;
}
static int quiet_printf(const char *format,...){(void)format;return 0;}
#define printf quiet_printf
#include "../../../../bsd/dev/mt6762_bif_observer.c"
#undef printf
static void reset(void)
{
    assert(!adc_mutex);now=100;duration=2000000;
    read_delay=interval_delay=lock_wait=0;operations=reads=writes=fail_at=0;
    requested=ready_reads=drift_reg=drift_after_request=missed_generation=0;
    bif_ready=bif_samples=bif_errors=bif_fault=bif_generation_rejections=bif_last_error=0;
    bif_raw=bif_ntc_raw=-1;
    memset(&bif_transport,0,sizeof(bif_transport));memset(&bif_observation,0,sizeof(bif_observation));
    memset(bif_config,0,sizeof(bif_config));memset(bif_baseline,0,sizeof(bif_baseline));
}
static void init(void){bif_init();assert(bif_ready && !bif_fault && reads==40 && !writes);operations=reads=0;}
static void invalid(void)
{
    struct mt6762_bif_observation value,sentinel;
    memset(&value,0xa5,sizeof(value));sentinel=value;
    assert(bif_observation_read(&value)==-ENXIO);
    assert(!memcmp(&value,&sentinel,sizeof(value)));
}
int main(void)
{
    int mv=1234;struct mt6762_bif_observation value;
    reset();invalid();init();assert(!bif_read(&mv));assert(mv==615 && writes==2);
    unsigned operation_count=operations;
    assert(!bif_observation_read(&value));
    assert(value.version==1 && value.size==72 && value.pmic_id==0x5730 && value.swcid==0x101);
    assert(value.tdet==4 && value.ntc_raw==1400 && value.bif_raw==4089);
    assert(!memcmp(value.config,words+3,sizeof(value.config)));
    assert(!value.reserved[0] && !value.reserved[1]);
    assert(value.acquired_abs==100 && value.expires_abs==2000100);
    assert(operations==operation_count); /* Getters never touch hardware. */
    now=value.expires_abs-1;assert(!bif_observation_read(&value));now++;invalid();
    /* New raw fields have no guessed calibrated/default encoding. A different
     * stable inherited value is captured verbatim, never normalized. */
    reset();drift_reg=0x11a6;init();assert(!bif_read(&mv));
    assert(!bif_observation_read(&value) && value.config[13]==0x48ac);
    /* Every enumerated word must remain equal, including HW/SW revisions. */
    for(unsigned i=0;i<20;i++) {
        reset();init();assert(!bif_read(&mv));requested=0;drift_reg=registers[i];
        unsigned old_writes=writes;mv=1234;assert(bif_read(&mv) && mv==1234);
        assert(bif_transport.fault && writes==old_writes);invalid();
        unsigned old_ops=operations;assert(bif_read(&mv) && operations==old_ops);
        reset();init();drift_reg=registers[i];drift_after_request=1;
        mv=1234;assert(bif_read(&mv) && mv==1234 && bif_transport.fault);invalid();
    }
    /* Initialization and each successful-path I/O can fail without partial output. */
    for(unsigned i=1;i<=40;i++) {reset();fail_at=i;bif_init();assert(!bif_ready && bif_fault && !writes);invalid();}
    for(unsigned i=1;i<=operation_count;i++) {
        reset();init();fail_at=i;mv=1234;assert(bif_read(&mv) && mv==1234 && bif_fault);invalid();
    }
    reset();init();missed_generation=1;mv=1234;
    assert(bif_read(&mv) && mv==1234 && !bif_fault && bif_generation_rejections==1);invalid();
    missed_generation=0;assert(!bif_read(&mv));
    /* The first state scan starts the lease; no post-I/O renewal. */
    reset();init();read_delay=100000;mv=1234;assert(bif_read(&mv) && mv==1234);invalid();
    reset();init();interval_delay=3000000;assert(bif_read(&mv));invalid();
    reset();init();interval_delay=100;assert(!bif_read(&mv));
    assert(!bif_observation_read(&value) && value.expires_abs==2000100);
    reset();init();duration=0;assert(bif_read(&mv) && !operations);
    reset();init();now=UINT64_MAX-10;assert(bif_read(&mv) && !operations);
    reset();init();assert(!bif_read(&mv));now=99;invalid();
    reset();init();assert(!bif_read(&mv));lock_wait=2000000;invalid();
    assert(bif_observation_read(NULL)==-EINVAL && bif_read(NULL)==-EINVAL);
    unsigned old_ops=operations;
    assert(bif_wr(NULL,0x1236,4)==-EPERM && bif_wr(NULL,0x11a2,0)==-EPERM && operations==old_ops);
    puts("native BIF complete raw-state coherence/acquisition/expiry/fault tests: PASS");
}
