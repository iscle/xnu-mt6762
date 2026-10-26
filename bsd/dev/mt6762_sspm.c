/* Bounded native SSPM attachment. Only PLATFORM liveness is sent automatically.
 * No CPU-DVFS initialization, vote, rail write, firmware reset or image load. */
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <sys/errno.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_sspm.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include <pexpert/pexpert.h>
#include "mt6762_sspm_protocol.h"
#include "../../tools/mt6762/hardware/cpu-power/mt6762_sspm_observer.h"

static uintptr_t data,ctrl,gic;
static int initialized,attached,sspm_alive=-1,sspm_errors,sspm_probes,sspm_transport_fault;
static uint64_t alive_deadline;
static LCK_GRP_DECLARE(sspm_group,"mt6762-sspm");
static LCK_MTX_DECLARE(sspm_mutex,&sspm_group);
static struct mt6762_sspm_transport transport;
SYSCTL_DECL(_kern_redwood);
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_sspm_alive,CTLFLAG_RD|CTLFLAG_LOCKED,&sspm_alive,0,"Last PLATFORM alive response: -1 unknown; not CPU-DVFS readiness");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_sspm_probes,CTLFLAG_RD|CTLFLAG_LOCKED,&sspm_probes,0,"Attempted active PLATFORM liveness transactions");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_sspm_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&sspm_errors,0,"SSPM attachment or protocol failures");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_sspm_fault,CTLFLAG_RD|CTLFLAG_LOCKED,&sspm_transport_fault,0,"Latched ownership/transport fault; no automatic reset or stale-ACK clear");

static int flag(const char *name)
{uint32_t v;return !mt6762_handoff_u32(name,&v) && v==1;}
struct passive_mapping {uintptr_t base[4];};
static int passive_read(void *context,unsigned region,uint32_t offset,uint32_t *value)
{
    const struct passive_mapping *m=context;
    if(!value || !mt6762_sspm_observer_address(region,offset))return -1;
    *value=*(volatile uint32_t *)(m->base[region]+offset);
    __asm__ volatile("dmb oshld":::"memory");return 0;
}
static void passive_words(unsigned pass,const char *group,const uint32_t *words,unsigned count)
{
    for(unsigned i=0;i<count;i+=4) {
        unsigned n=count-i<4?count-i:4;
        kprintf("MT6762_SSPM_RAW pass=%u group=%s word=%u count=%u %08x %08x %08x %08x\n",
            pass,group,i,n,words[i],n>1?words[i+1]:0,n>2?words[i+2]:0,n>3?words[i+3]:0);
    }
}
static void passive_probe(void)
{
    struct passive_mapping m;
    struct mt6762_sspm_observation_pair p;
    m.base[MT6762_OBS_CSRAM]=(uintptr_t)mt6762_map_mmio(0x00110c00,0x1400);
    m.base[MT6762_OBS_DATA]=(uintptr_t)mt6762_map_mmio(0x10450000,0x100);
    m.base[MT6762_OBS_CTRL]=(uintptr_t)mt6762_map_mmio(0x10451000,8);
    m.base[MT6762_OBS_GIC]=(uintptr_t)mt6762_map_mmio(0x0c000000,0x1000);
    for(unsigned i=0;i<4;i++)if(!m.base[i]) {
        kprintf("MT6762_SSPM_OBSERVE error=mapping region=%u\n",i);return;
    }
    if(mt6762_sspm_observe_pair(passive_read,&m,&p)) {
        kprintf("MT6762_SSPM_OBSERVE error=read\n");return;
    }
    kprintf("MT6762_SSPM_OBSERVE version=1 passes=2 words=174 stable_groups=%03x guards=%d c62_representation=%d ownership=0 liveness=unknown\n",
        p.stable_groups,mt6762_sspm_observer_guards(&p),mt6762_sspm_observer_c62(&p));
    /* Equal groups need one raw copy; a changing pair retains both complete
     * passes. No word is interpreted as an initialized-controller grant. */
    for(unsigned pass=0;pass<(p.stable_groups==MT6762_OBS_ALL?1u:2u);pass++) {
        const struct mt6762_sspm_observation *s=&p.sample[pass];
        passive_words(pass,"guards",s->guards,5);passive_words(pass,"pvt",s->pvt,144);
        passive_words(pass,"eem",s->eem,3);passive_words(pass,"ppm",s->ppm,2);
        passive_words(pass,"voltage",s->voltage,3);passive_words(pass,"index",s->index,3);
        passive_words(pass,"vote",s->vote,3);passive_words(pass,"mailbox",s->mailbox,9);
        passive_words(pass,"irq",s->irq,2);
    }
    kprintf("MT6762_SSPM_OBSERVE end=1 writes=0\n");
}
static int read_word(void *unused,unsigned region,uint32_t offset,uint32_t *out)
{
    uintptr_t base=region==MT6762_SSPM_DATA?data:ctrl;
    (void)unused;
    if(!out || (offset&3) || offset>=(region==MT6762_SSPM_DATA?0x100u:8u))return -1;
    *out=*(volatile uint32_t *)(base+offset);
    __asm__ volatile("dmb oshld":::"memory");return 0;
}
static int write_word(void *unused,unsigned region,uint32_t offset,uint32_t value)
{
    uintptr_t base=region==MT6762_SSPM_DATA?data:ctrl;
    (void)unused;
    if((offset&3) || offset>=(region==MT6762_SSPM_DATA?0x100u:8u))return -1;
    __asm__ volatile("dmb oshst":::"memory");
    *(volatile uint32_t *)(base+offset)=value;
    return 0;
}
static void barrier(void *unused) {(void)unused;__asm__ volatile("dsb sy":::"memory");}
static void wait_us(void *unused,unsigned us) {(void)unused;delay(us);}
/* The former IRQ consumer must be quiesced, otherwise it can steal our ACK. */
static int irq_quiesced(void)
{
    const unsigned intid=237; /* Actual DT mailbox0: SPI205 + 32. */
    uint32_t enabled=*(volatile uint32_t *)(gic+0x100+(intid/32)*4);
    uint32_t active=*(volatile uint32_t *)(gic+0x300+(intid/32)*4);
    __asm__ volatile("dmb oshld":::"memory");
    return !((enabled|active)&(1u<<(intid%32)));
}
int mt6762_sspm_probe_alive(void)
{
    const uint32_t command[3]={0xdead,0,0};
    uint32_t acknowledgement=0;
    int e;
    lck_mtx_lock(&sspm_mutex);
    if(!attached || transport.fault) {lck_mtx_unlock(&sspm_mutex);return -ENXIO;}
    sspm_alive=-1;alive_deadline=0;
    if(!irq_quiesced()) {transport.fault=1;e=MT6762_SSPM_BUSY;}
    else {
        sspm_probes++;
        e=mt6762_sspm_exchange(&transport,0,command,3,&acknowledgement,10000);
    }
    sspm_transport_fault=transport.fault;
    if(e)sspm_errors++;
    else {
        sspm_alive=acknowledgement!=0;
        if(sspm_alive)clock_interval_to_deadline(10000,NSEC_PER_MSEC,&alive_deadline);
    }
    lck_mtx_unlock(&sspm_mutex);
    return e ? (e==MT6762_SSPM_TIMEOUT?-ETIMEDOUT:-EIO) : (acknowledgement?0:-ENXIO);
}
int mt6762_sspm_alive_recent(void)
{
    uint64_t now;
    int alive;
    lck_mtx_lock(&sspm_mutex);
    clock_get_uptime(&now);
    alive=attached && !transport.fault && sspm_alive==1 && now<alive_deadline;
    lck_mtx_unlock(&sspm_mutex);
    return alive;
}
static void worker(__unused void *parameter,__unused wait_result_t result)
{
    for(;;) {
        delay_for_interval(5000,NSEC_PER_MSEC);
        (void)mt6762_sspm_probe_alive();
    }
}
void mt6762_sspm_init(void)
{
    static int observed;
    thread_t thread;
    int e;
    uint32_t pending_in,pending_out;
    if(!mt6762_platform_ready())return;
    /* Separate diagnostic admission breaks the circular dependency on an
     * ownership assertion merely to inspect inherited state. This mode never
     * enters the active transport, even if both properties were supplied. */
    if(flag("sspm-inherited-probe")) {
        if(!observed && !initialized) {observed=1;passive_probe();}
        return;
    }
    if(initialized || !flag("sspm-mailbox-owned"))return;
    initialized=1;
    /* Mailbox ownership does not preserve firmware or its dynamic shared
     * DRAM allocation. A physical loader must reserve both from XNU's page
     * allocator and retain the active image's EMI access before any command.
     * The explicitly synthetic fixture has no resident firmware/DRAM image. */
    if(!flag("lab-fixture") && !flag("sspm-firmware-preserved")) {
        sspm_errors++;
        printf("MT6762 SSPM: firmware/shared-memory preservation not established\n");
        return;
    }
    data=(uintptr_t)mt6762_map_mmio(0x10450000,0x100);
    ctrl=(uintptr_t)mt6762_map_mmio(0x10451000,8);
    gic=(uintptr_t)mt6762_map_mmio(0x0c000000,0x1000);
    if(!data || !ctrl || !gic || !irq_quiesced()) {
        sspm_errors++;printf("MT6762 SSPM: mailbox mapping/IRQ ownership rejected\n");return;
    }
    if(read_word(NULL,MT6762_SSPM_CTRL,0,&pending_in) ||
       read_word(NULL,MT6762_SSPM_CTRL,4,&pending_out) ||
       ((pending_in|pending_out)&3)) {
        sspm_errors++;sspm_transport_fault=1;
        printf("MT6762 SSPM: inherited PLATFORM/CPU traffic rejected, no stale status cleared\n");return;
    }
    transport.io=(struct mt6762_sspm_io){NULL,read_word,write_word,barrier,wait_us};
    transport.owned_pins=3; /* PLATFORM and CPU-DVFS AP pins, as handoff requires. */
    attached=1;
    e=mt6762_sspm_probe_alive();
    printf("MT6762 SSPM: PLATFORM probe result=%d alive=%d fault=%d; CPU-DVFS control remains disabled\n",
        e,sspm_alive,sspm_transport_fault);
    if(!transport.fault && kernel_thread_start(worker,NULL,&thread)==KERN_SUCCESS)
        thread_deallocate(thread);
}
