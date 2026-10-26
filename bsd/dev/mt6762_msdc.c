/* SPDX-License-Identifier: MIT
 * Owned inherited MSDC0 PIO consumer. No cold init, DMA, reset or media writes.
 * The optional physical producer admits only the audited synchronous LK
 * handoff. Live rail/card checks below remain mandatory before publication.
 */
#include <sys/mt6762_msdc.h>
#if defined(ARM64_BOARD_CONFIG_MT6762)
#include <kern/clock.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_power.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include "mt6762_msdc_protocol.h"
#include "../../tools/mt6762/hardware/storage/mt6762_msdc_admission.h"

static struct mt6762_msdc engine;
static uintptr_t controller,gic,top,infra,pll,gpio,pads,tuning;
static int started,lab,ready,fault,last_error,reads,sectors;
static uint32_t last_response;
static int response_observed;
static uint32_t issued_command,ext_bytes;
static uint8_t ext_snapshot[512];
static uint32_t expected_pad_drive,expected_hclk;
static uint32_t top_tune[12],controller_tune[18];
static const uint16_t tune_regs[18]={0x04,0xb0,0xb4,0xb8,0xf0,0xf4,0xf8,0xfc,
    0x100,0x104,0x180,0x184,0x188,0x18c,0x190,0x194,0x198,0x19c};
static uint32_t pll_snapshot[6];
/* All transport callbacks run under msdc_bsd_lock after publication. */
static struct mt6762_msdc_admission admission;
static uint64_t perf_sectors,perf_read_us,perf_read_max_us;
static uint64_t perf_start_us,perf_report_us;
static int perf_started;
static uint64_t time_us(void *);

SYSCTL_DECL(_kern_redwood);
static int msdc_sysctl SYSCTL_HANDLER_ARGS
{
    int *field=NULL;
    switch(arg2) {
    case 0:field=&ready;break;case 1:field=&fault;break;
    case 2:field=&last_error;break;case 3:field=&reads;break;case 4:field=&sectors;break;
    default:return EINVAL;
    }
    int value=__atomic_load_n(field,__ATOMIC_ACQUIRE);
    return sysctl_handle_int(oidp,&value,0,req);
}
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_msdc_ready,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,msdc_sysctl,"I","Owned inherited PIO/card accepted and read-only disk published");
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_msdc_fault,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,1,msdc_sysctl,"I","Terminal inherited PIO ownership/transaction fault");
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_msdc_last_error,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,2,msdc_sysctl,"I","Last negative protocol code, or negative BSD publication error");
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_msdc_reads,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,3,msdc_sysctl,"I","Completed successful512-byte media reads; excludes EXT_CSD");
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_msdc_sectors,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,4,msdc_sysctl,"I","Capacity corroborated by actual EXT_CSD; transport readiness separate");

static uint32_t r32(uintptr_t base,unsigned offset)
{
    uint32_t value=*(volatile uint32_t *)(base+offset);
    __asm__ volatile("dsb oshld":::"memory");
    return value;
}
static int flag(const char *name)
{
    uint32_t value;
    return !mt6762_handoff_u32(name,&value) && value==1;
}
static int irq_quiet(void)
{
    const unsigned group=111/32,bit=111%32;
    uint32_t mask=1u<<bit;
    /* The producer must mask/quiesce it. Never acknowledge another owner. */
    return gic && !(r32(gic,0)&0x80000000u) &&
        !(r32(gic,0x100+group*4)&mask) &&
        !(r32(gic,0x200+group*4)&mask) &&
        !(r32(gic,0x300+group*4)&mask) &&
        !(r32(gic,0xc00+(111/16)*4)&(3u<<((111%16)*2)));
}
static int clocks_stable(void)
{
    uint32_t config=r32(top,0x70),values[6],parent_hz,hclk_hz,card_hz;
    if((config&0x8783)!=0x101 || (r32(infra,0x94)&4) ||
       (r32(infra,0xc8)&(1u<<9)))return 0;
    const unsigned offsets[6]={0x27c,0x280,0x288,0x23c,0x240,0x248};
    for(unsigned i=0;i<6;i++) {
        values[i]=r32(pll,offsets[i]);
        if(values[i]!=pll_snapshot[i])return 0;
    }
    if(mt6762_msdc_pll_hz(values[0],values[1],values[2],&parent_hz) ||
       !(values[3]&(1u<<23)) ||
       mt6762_msdc_pll_hz(values[3],values[4],values[5],&hclk_hz) ||
       hclk_hz/4!=expected_hclk ||
       mt6762_msdc_sclk_hz(parent_hz,engine.config.expected_cfg,&card_hz) ||
       card_hz!=engine.config.card_clock_hz)return 0;
    for(unsigned i=0;i<6;i++)if(values[i]!=r32(pll,offsets[i]))return 0;
    return config==r32(top,0x70) && !(r32(infra,0x94)&4) &&
        !(r32(infra,0xc8)&(1u<<9));
}
static int pads_stable(void)
{
    uint32_t trap=r32(gpio,0x6f0)&0x6000;
    uint32_t mux0=trap?0x11111100:0x22222200;
    uint32_t mux1=trap?0x00111111:0x00222222;
    if((r32(gpio,0x3f0)&0x77777700)!=mux0 ||
       (r32(gpio,0x400)&0x00777777)!=mux1 ||
       (r32(pads,0)&0x001fffc0)!=expected_pad_drive ||
       (r32(pads,0x30)&0xfff)!=0x401 ||
       (r32(pads,0x50)&0xfff)!=0xbfe ||
       (r32(pads,0x60)&0xfff)!=0x401 ||
       (r32(pads,0x90)&0x00fffff0) || (r32(pads,0x70)&0xfffffffc))return 0;
    for(unsigned i=0;i<12;i++)if(r32(tuning,i*4)!=top_tune[i])return 0;
    for(unsigned i=0;i<18;i++)if(r32(controller,tune_regs[i])!=controller_tune[i])return 0;
    return trap==(r32(gpio,0x6f0)&0x6000);
}
static int rails_stable(void)
{
    /* Fixed narrow stock3.0V VEMC +1.8V I/O. DA_EN is the selected regulator
     * driver's is_enabled input, not an analog voltage measurement. */
    static const uint16_t address[]={0x1988,0x1958,0x1c20,0x1996,0x1966};
    static const uint16_t mask[]={1,1,0x700,0x8000,0x8000};
    static const uint16_t expected[]={1,1,0x300,0x8000,0x8000};
    uint16_t values[5],again;
    for(unsigned i=0;i<5;i++)
        if(mt6762_pwrap_read16(address[i],&values[i]) ||
           (values[i]&mask[i])!=expected[i])return 0;
    for(unsigned i=0;i<5;i++)
        if(mt6762_pwrap_read16(address[i],&again) ||
           (again&mask[i])!=(values[i]&mask[i]))return 0;
    return 1;
}
static int admit_before(void *unused)
{
    (void)unused;
    return mt6762_platform_ready() && irq_quiet() && clocks_stable()?0:-1;
}
static int admit_static(void *unused)
{(void)unused;return pads_stable() && rails_stable()?0:-1;}
static int admit_after(void *unused)
{(void)unused;return clocks_stable() && irq_quiet()?0:-1;}
static int admit(void *unused)
{
    (void)unused;
    /* Lab fixtures model protocol state only; no physical gates are inferred. */
    if(lab)return mt6762_platform_ready() && irq_quiet()?0:-1;
    const struct mt6762_msdc_admission_io io={NULL,time_us,
        admit_before,admit_static,admit_after};
    return mt6762_msdc_admission_check(&admission,&io);
}
static uint32_t read32(void *unused,uint32_t offset)
{
    (void)unused;
    uint32_t value=r32(controller,offset);
    if(offset==0x40) {last_response=value;response_observed=1;}
    if(offset==0x1c && issued_command==0x02000888 && ext_bytes<=508) {
        for(unsigned i=0;i<4;i++)ext_snapshot[ext_bytes++]=(uint8_t)(value>>(i*8));
    }
    return value;
}
static void write32(void *unused,uint32_t offset,uint32_t value)
{
    (void)unused;
    if(offset==0x34) {
        last_response=0;response_observed=0;issued_command=value;
        if(value==0x02000888)ext_bytes=0;
    }
    *(volatile uint32_t *)(controller+offset)=value;
    __asm__ volatile("dsb sy":::"memory");
}
static uint64_t time_us(void *unused)
{
    uint64_t ticks,ns;
    (void)unused;clock_get_uptime(&ticks);absolutetime_to_nanoseconds(ticks,&ns);
    return ns/1000;
}
static void delay_us(void *unused,uint32_t us)
{
    uint64_t interval;
    (void)unused;
    clock_interval_to_absolutetime_interval(us,NSEC_PER_USEC,&interval);
    uint64_t start=mach_absolute_time();
    /* GenericARMCPU has no powergate latency: delay_for_interval(1us)
     * schedules away on every not-ready poll. These protocol pauses are
     * short; keep IRQs/preemption enabled and poll the proven timer instead.
     * Do not use WFE, whose completion requires an event. */
    while(mach_absolute_time()-start<interval)
        __asm__ volatile("yield" ::: "memory");
}
static void performance_report(uint64_t now,int force)
{
    if(!force && now>=perf_report_us && now-perf_report_us<30000000)return;
    perf_report_us=now;
    kprintf("MT6762_MSDC_PERF lab=%u sectors=%llu bytes=%llu wall_us=%llu read_us=%llu read_max_us=%llu admissions=%llu full=%llu reused=%llu full_us=%llu full_max_us=%llu slow_full=%llu admission_errors=%llu clock_reverse=%llu\n",
        lab,perf_sectors,perf_sectors*512,now>=perf_start_us?now-perf_start_us:0,
        perf_read_us,perf_read_max_us,admission.calls,admission.full,
        admission.reused,admission.full_us,admission.full_max_us,
        admission.slow_full,admission.failures,admission.clock_reversals);
}
static int read_sector(uint64_t lba,void *out)
{
    if(!__atomic_load_n(&ready,__ATOMIC_ACQUIRE))return ENXIO;
    uint64_t start=time_us(NULL);
    if(!perf_started) {perf_started=1;perf_start_us=perf_report_us=start;}
    int error=mt6762_msdc_read512(&engine,lba,out);
    uint64_t end=time_us(NULL);
    if(end>=start) {
        uint64_t elapsed=end-start;
        perf_read_us+=elapsed;
        if(elapsed>perf_read_max_us)perf_read_max_us=elapsed;
    }
    if(error) {
        mt6762_msdc_admission_invalidate(&admission);
        __atomic_store_n(&last_error,error,__ATOMIC_RELEASE);
        if(engine.faulted) {
            __atomic_store_n(&fault,1,__ATOMIC_RELEASE);
            __atomic_store_n(&ready,0,__ATOMIC_RELEASE);
            printf("MT6762 MSDC: terminal read failure %d; lba=%llu command=%x phase=%u bytes=%u irq=%x stalled_us=%llu; no reset/retry\n",
                error,lba,engine.last_command,engine.wait_phase,engine.data_bytes,
                engine.last_irq,engine.stalled_us);
        }
        performance_report(end,1);
        return error==MT6762_MSDC_ARGUMENT?EINVAL:
            (error==MT6762_MSDC_TIMEOUT?ETIMEDOUT:EIO);
    }
    mt6762_msdc_admission_sector_done(&admission);
    perf_sectors++;
    performance_report(end,perf_sectors==1);
    int count=__atomic_load_n(&reads,__ATOMIC_RELAXED);
    if(count<2147483647)__atomic_store_n(&reads,count+1,__ATOMIC_RELEASE);
    return 0;
}
static int physical_contract(void)
{
    static const char * const required[]={"msdc-irq-owned","msdc-clock-owned",
        "msdc-pads-owned","msdc-rails-preserved","msdc-tuning-preserved",
        "msdc-card-quiesced","msdc-writes-drained","msdc-sector-addressed",
        "msdc-ocr-verified","msdc-handoff-producer-version"};
    for(unsigned i=0;i<sizeof(required)/sizeof(required[0]);i++)if(!flag(required[i]))return -1;
    uint32_t ocr;
    if(mt6762_handoff_u32("msdc-ocr",&ocr) || (ocr&0xc0000000)!=0xc0000000 ||
       mt6762_handoff_u32("msdc-pad-drive",&expected_pad_drive) ||
       mt6762_handoff_u32("msdc-hclk-hz",&expected_hclk) || !expected_hclk)return -1;
    uint32_t normal=(3u<<6)|(3u<<9)|(3u<<12)|(3u<<15)|(3u<<18);
    uint32_t fast=(4u<<6)|(3u<<9)|(4u<<12)|(4u<<15)|(3u<<18);
    /* Actual LK capture15 preserves GEAR1 on all five groups at48MHz DDR.
     * Do not rewrite those pads to the later Android GEAR3/4 defaults. */
    uint32_t inherited_lk=(1u<<6)|(1u<<9)|(1u<<12)|(1u<<15)|(1u<<18);
    if(expected_pad_drive!=normal && expected_pad_drive!=fast && expected_pad_drive!=inherited_lk)return -1;
    static const char * const pll_names[]={"msdc-pll-con0","msdc-pll-con1","msdc-pll-power",
        "msdc-mainpll-con0","msdc-mainpll-con1","msdc-mainpll-power"};
    for(unsigned i=0;i<6;i++)if(mt6762_handoff_u32(pll_names[i],&pll_snapshot[i]))return -1;
    for(unsigned i=0;i<12;i++) {
        char name[32];snprintf(name,sizeof(name),"msdc-top-tune-%u",i);
        if(mt6762_handoff_u32(name,&top_tune[i]))return -1;
    }
    for(unsigned i=0;i<18;i++) {
        char name[32];snprintf(name,sizeof(name),"msdc-controller-tune-%u",i);
        if(mt6762_handoff_u32(name,&controller_tune[i]))return -1;
    }
    top=(uintptr_t)mt6762_map_mmio(0x10000000,0x1000);
    infra=(uintptr_t)mt6762_map_mmio(0x10001000,0x1000);
    pll=(uintptr_t)mt6762_map_mmio(0x1000c000,0x1000);
    gpio=(uintptr_t)mt6762_map_mmio(0x10005000,0x1000);
    pads=(uintptr_t)mt6762_map_mmio(0x10002000,0x1000);
    tuning=(uintptr_t)mt6762_map_mmio(0x11cd0000,0x1000);
    return top && infra && pll && gpio && pads && tuning?0:-1;
}
void mt6762_storage_init(void)
{
    if(__atomic_exchange_n(&started,1,__ATOMIC_ACQ_REL))return;
    if(!mt6762_platform_ready() || !flag("msdc-owned") || !flag("msdc-inherited-verified"))return;
    struct mt6762_msdc_config config={0};
    uint32_t count;
    if(mt6762_handoff_u32("msdc-sector-count",&count) || !count || count>2147483647 ||
       mt6762_handoff_u32("msdc-rca",&config.rca) ||
       mt6762_handoff_u32("msdc-cfg",&config.expected_cfg) ||
       mt6762_handoff_u32("msdc-sdc-cfg",&config.expected_sdc_cfg) ||
       mt6762_handoff_u32("msdc-timeout-us",&config.timeout_us) ||
       mt6762_handoff_u32("msdc-card-clock-hz",&config.card_clock_hz)) {
        last_error=MT6762_MSDC_ARGUMENT;
        printf("MT6762 MSDC: incomplete bounded inherited configuration\n");return;
    }
    config.sector_count=count;
    lab=flag("lab-fixture");
    if(!lab && physical_contract()) {
        last_error=MT6762_MSDC_OWNERSHIP;
        kprintf("MT6762_MSDC refused physical handoff contract\n");
        printf("MT6762 MSDC: physical producer/clock/pad/rail/tuning contract missing; unavailable\n");return;
    }
    controller=(uintptr_t)mt6762_map_mmio(0x11230000,0x10000);
    gic=(uintptr_t)mt6762_map_mmio(0x0c000000,0x10000);
    if(!controller || !gic) {
        last_error=MT6762_MSDC_STATE;
        printf("MT6762 MSDC: MMIO mapping unavailable\n");return;
    }
    struct mt6762_msdc_io io={NULL,admit,read32,write32,time_us,delay_us};
    int error=mt6762_msdc_init(&engine,&io,&config);
    /* Publication starts a new bounded observation window. */
    mt6762_msdc_admission_invalidate(&admission);
    if(ext_bytes==512) {
        uint32_t card_sectors=(uint32_t)ext_snapshot[212]|((uint32_t)ext_snapshot[213]<<8)|
            ((uint32_t)ext_snapshot[214]<<16)|((uint32_t)ext_snapshot[215]<<24);
        kprintf("MT6762_MSDC_EXT bytes=%u sectors=%u cqe=%x partition=%x bus_width=%x timing=%x revision=%x card_type=%x bkops=%x events=%x\n",
            ext_bytes,card_sectors,ext_snapshot[15],ext_snapshot[179],ext_snapshot[183],
            ext_snapshot[185],ext_snapshot[192],ext_snapshot[196],ext_snapshot[246],
            ext_snapshot[54]|((unsigned)ext_snapshot[55]<<8));
    }
    if(error) {
        last_error=error;fault=engine.faulted?1:0;
        kprintf("MT6762_MSDC refused error=%d command=%x argument=%x phase=%u bytes=%u irq=%x stalled_us=%llu response_seen=%d r1=%x\n",
            error,engine.last_command,engine.last_argument,engine.wait_phase,
            engine.data_bytes,engine.last_irq,engine.stalled_us,response_observed,last_response);
        printf("MT6762 MSDC: inherited admission/card read failed %d; no reset\n",error);return;
    }
    error=mt6762_msdc_publish(config.sector_count,read_sector);
    if(error) {
        last_error=-error;fault=1;engine.faulted=1;
        printf("MT6762 MSDC: read-only BSD publication failed %d\n",error);return;
    }
    __atomic_store_n(&sectors,(int)count,__ATOMIC_RELEASE);
    __atomic_store_n(&ready,1,__ATOMIC_RELEASE);
    kprintf("MT6762_MSDC_READY lab=%u sectors=%u hz=%u rca=%u readonly=1\n",
        lab,count,config.card_clock_hz,config.rca);
    kprintf("MT6762_MSDC_ADMISSION static_reuse_us=%u max_sectors=%u dynamic_each_phase=1 continuous_rail_measurement=0\n",
        MT6762_MSDC_STATIC_US,MT6762_MSDC_STATIC_SECTORS);
    printf("MT6762 MSDC: %s inherited PIO, %u sectors, %u Hz, read-only /dev/mtkemmc0; no reset/DMA\n",
        lab?"SYNTHETIC LAB":"verified handoff",count,config.card_clock_hz);
}
#else
void mt6762_storage_init(void) {}
#endif
