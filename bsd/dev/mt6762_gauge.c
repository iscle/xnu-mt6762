/* Owned MT6357 gauge observation; no gauge reset, calibration writes or SOC. */
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <sys/errno.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_power.h>
#include <sys/mt6762_gauge.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include "mt6762_gauge_protocol.h"
static LCK_GRP_DECLARE(gauge_group,"mt6762-gauge");
static LCK_MTX_DECLARE(gauge_mutex,&gauge_group);
static struct mt6762_gauge_transport transport;
static unsigned rfg,tune;
static uint16_t expected[5];
static const uint16_t config_regs[5]={0xd08,0xc8e,0xc90,0xd94,0xd96};
static int started,valid,current_ua,errors,samples,transport_fault;
static int raw_current=-1,have_ticks;
static uint64_t last_ticks,deadline;
SYSCTL_DECL(_kern_redwood);
static int gauge_sysctl SYSCTL_HANDLER_ARGS
{
    uint64_t now;
    int value;
    clock_get_uptime(&now);
    lck_mtx_lock(&gauge_mutex);
    int fresh=valid && now<deadline;
    value=arg2 ? fresh : (fresh?current_ua:(-2147483647-1));
    lck_mtx_unlock(&gauge_mutex);
    return sysctl_handle_int(oidp,&value,0,req);
}
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_gauge_current_ua,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,gauge_sysctl,"I","Calibrated gauge snapshot current, positive charge; INT_MIN invalid/stale");
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_gauge_current_valid,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,1,gauge_sysctl,"I","Current has completed snapshot and advancing NTER, unexpired");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_gauge_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&samples,0,"Completed gauge snapshots; includes initial liveness baseline");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_gauge_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&errors,0,"Gauge admission/transaction/configuration failures");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_gauge_fault,CTLFLAG_RD|CTLFLAG_LOCKED,&transport_fault,0,"Latched protocol/calibration ownership failure");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_gauge_raw_current,CTLFLAG_RD|CTLFLAG_LOCKED,&raw_current,0,"Latest completed raw current, not calibrated freshness; -1 absent");
int mt6762_gauge_current_read(int *ua)
{
    uint64_t now;
    int e=-ENXIO;
    if(!ua)return -EINVAL;
    clock_get_uptime(&now);
    lck_mtx_lock(&gauge_mutex);
    if(valid && now<deadline) {*ua=current_ua;e=0;}
    lck_mtx_unlock(&gauge_mutex);return e;
}
static int flag(const char *name)
{uint32_t v;return !mt6762_handoff_u32(name,&v) && v==1;}
static int read16(void *unused,uint16_t reg,uint16_t *value)
{(void)unused;return mt6762_pwrap_read16(reg,value);}
static int write16(void *unused,uint16_t reg,uint16_t value)
{(void)unused;return reg==0xd0a?mt6762_pwrap_write16(reg,value):-EINVAL;}
static void wait_us(void *unused,unsigned us) {(void)unused;delay(us);}
static int config_matches(void)
{
    uint16_t v;
    if(mt6762_pwrap_read16(8,&v) || (v>>8)!=0x57)return 0;
    for(unsigned i=0;i<5;i++)if(mt6762_pwrap_read16(config_regs[i],&v) || v!=expected[i])return 0;
    return 1;
}
static void observe(void)
{
    struct mt6762_gauge_snapshot snapshot;
    int value;
    lck_mtx_lock(&gauge_mutex);
    valid=0;deadline=0;
    if(transport.fault)goto done;
    if(!config_matches() || mt6762_gauge_capture(&transport,&snapshot) || !config_matches() ||
       mt6762_gauge_current(snapshot.current,rfg,tune,&value)) {
        transport.fault=1;transport_fault=1;errors++;goto done;
    }
    samples++;raw_current=snapshot.current;
    if(have_ticks && snapshot.ticks!=last_ticks && !mt6762_gauge_progress(last_ticks,snapshot.ticks)) {
        transport.fault=1;transport_fault=1;errors++;goto done;
    }
    if(have_ticks && mt6762_gauge_progress(last_ticks,snapshot.ticks)) {
        current_ua=value;valid=1;
        clock_interval_to_deadline(2000,NSEC_PER_MSEC,&deadline);
    }
    last_ticks=snapshot.ticks;have_ticks=1;
done:
    lck_mtx_unlock(&gauge_mutex);
}
static void worker(__unused void *parameter,__unused wait_result_t result)
{
    for(;;) {observe();delay_for_interval(1000,NSEC_PER_MSEC);}
}
void mt6762_gauge_init(void)
{
    static const char *names[5]={"fgauge-con0","fgauge-efuse-gain","fgauge-efuse-offset","fgauge-adjust-offset","fgauge-gain"};
    uint32_t v;
    thread_t thread;
    if(started || !mt6762_platform_ready() || !flag("fgauge-owned") || !flag("fgauge-calibration-verified"))return;
    started=1;
    if(mt6762_handoff_u32("fgauge-rfg",&rfg) || mt6762_handoff_u32("fgauge-car-tune",&tune) ||
       !rfg || rfg>10000 || !tune || tune>10000)goto rejected;
    for(unsigned i=0;i<5;i++) {
        if(mt6762_handoff_u32(names[i],&v) || v>0xffff)goto rejected;
        expected[i]=(uint16_t)v;
    }
    if(!(expected[0]&1) || !config_matches())goto rejected;
    transport.io=(struct mt6762_gauge_io){NULL,read16,write16,wait_us};
    printf("MT6762 gauge: owned calibrated snapshot observer; current awaits NTER progression, SOC unavailable\n");
    if(kernel_thread_start(worker,NULL,&thread)==KERN_SUCCESS)thread_deallocate(thread);
    return;
rejected:
    errors++;transport_fault=1;
    printf("MT6762 gauge: missing or mismatched live calibration handoff rejected\n");
}
