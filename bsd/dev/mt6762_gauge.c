/* Owned MT6357 current/CAR observation; no gauge reset, calibration writes or SOC. */
#ifndef MT6762_GAUGE_HOST_TEST
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
#endif
#include "mt6762_gauge_protocol.h"
static LCK_GRP_DECLARE(gauge_group,"mt6762-gauge");
static LCK_MTX_DECLARE(gauge_mutex,&gauge_group);
static struct mt6762_gauge_transport transport;
static unsigned rfg,tune;
static uint16_t expected[5];
static const uint16_t config_regs[5]={0xd08,0xc8e,0xc90,0xd94,0xd96};
static int valid,errors,samples,transport_fault,freshness_rejections;
/* Private native snapshot: signed accumulated charge is not remaining capacity.
 * Keep the existing Apple-facing battery ABI and generated IIG headers intact. */
struct gauge_observation {
    int current_ua;
    int64_t charge_uah;
    uint64_t acquired_abs,expires_abs;
};
#ifndef MT6762_GAUGE_HOST_TEST
extern int mt6762_inherited_gauge_snapshot(int *,int64_t *,uint64_t *,uint64_t *);
#endif
static struct gauge_observation observation;
static int raw_current=-1,have_ticks;
static uint64_t last_ticks;
static int observation_read(struct gauge_observation *out)
{
    uint64_t now;
    int e=-ENXIO;
    if(!out)return -EINVAL;
#ifndef MT6762_GAUGE_HOST_TEST
    e=mt6762_inherited_gauge_snapshot(&out->current_ua,&out->charge_uah,&out->acquired_abs,&out->expires_abs);
    if(e!=-ENXIO)return e;
#endif
    lck_mtx_lock(&gauge_mutex);
    clock_get_uptime(&now);
    if(valid && now>=observation.acquired_abs && now<observation.expires_abs) {
        *out=observation;e=0;
    }
    lck_mtx_unlock(&gauge_mutex);
    return e;
}
#ifndef MT6762_GAUGE_HOST_TEST
static int started;
SYSCTL_DECL(_kern_hakios);
static int gauge_sysctl SYSCTL_HANDLER_ARGS
{
    struct gauge_observation value_snapshot;
    int fresh=!observation_read(&value_snapshot);
    int value=arg2 ? fresh : (fresh?value_snapshot.current_ua:(-2147483647-1));
    return sysctl_handle_int(oidp,&value,0,req);
}
static int gauge_charge_sysctl SYSCTL_HANDLER_ARGS
{
    struct gauge_observation value_snapshot;
    int64_t value=observation_read(&value_snapshot)?INT64_MIN:value_snapshot.charge_uah;
    return sysctl_handle_quad(oidp,&value,0,req);
}
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_gauge_current_ua,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,gauge_sysctl,"I","Calibrated gauge snapshot current, positive charge; INT_MIN invalid/stale");
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_gauge_current_valid,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,1,gauge_sysctl,"I","Current has completed snapshot and advancing NTER, unexpired");
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_gauge_charge_uah,CTLTYPE_QUAD|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,gauge_charge_sysctl,"Q","Signed calibrated accumulated Coulomb counter, not SOC/capacity; INT64_MIN invalid/stale");
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_gauge_charge_valid,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,1,gauge_sysctl,"I","Charge shares current latch, calibration, NTER liveness and acquisition expiry");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_gauge_freshness_rejections,CTLFLAG_RD|CTLFLAG_LOCKED,&freshness_rejections,0,"Nonadvancing NTER or completed acquisition already expired");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_gauge_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&samples,0,"Completed gauge snapshots; includes initial liveness baseline");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_gauge_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&errors,0,"Gauge admission/transaction/configuration failures");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_gauge_fault,CTLFLAG_RD|CTLFLAG_LOCKED,&transport_fault,0,"Latched protocol/calibration ownership failure");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_gauge_raw_current,CTLFLAG_RD|CTLFLAG_LOCKED,&raw_current,0,"Latest completed raw current, not calibrated freshness; -1 absent");
#endif
int mt6762_gauge_current_snapshot(int *ua,uint64_t *expires_abs)
{
    struct gauge_observation value;
    if(!ua)return -EINVAL;
    int e=observation_read(&value);
    if(!e) {
        *ua=value.current_ua;
        if(expires_abs)*expires_abs=value.expires_abs;
    }
    return e;
}
int mt6762_gauge_current_read(int *ua)
{
    return mt6762_gauge_current_snapshot(ua,NULL);
}
#ifndef MT6762_GAUGE_HOST_TEST
static int flag(const char *name)
{uint32_t v;return !mt6762_handoff_u32(name,&v) && v==1;}
static int read16(void *unused,uint16_t reg,uint16_t *value)
{(void)unused;return mt6762_pwrap_read16(reg,value);}
static int write16(void *unused,uint16_t reg,uint16_t value)
{(void)unused;return reg==0xd0a?mt6762_pwrap_write16(reg,value):-EINVAL;}
static void wait_us(void *unused,unsigned us) {(void)unused;delay(us);}
#endif
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
    struct gauge_observation next;
    uint64_t now,duration;
    lck_mtx_lock(&gauge_mutex);
    valid=0;observation.expires_abs=0;
    if(transport.fault)goto done;
    /* Start the lease before any PMIC/config/latch I/O. Slow successful reads
     * must not receive a new two-second lease after their acquisition ends. */
    clock_get_uptime(&next.acquired_abs);
    clock_interval_to_absolutetime_interval(2000,NSEC_PER_MSEC,&duration);
    if(!duration || UINT64_MAX-next.acquired_abs<duration) {
        freshness_rejections++;goto done;
    }
    next.expires_abs=next.acquired_abs+duration;
    if(!config_matches() || mt6762_gauge_capture(&transport,&snapshot) || !config_matches() ||
       mt6762_gauge_current(snapshot.current,rfg,tune,&next.current_ua) ||
       mt6762_gauge_charge(snapshot.car_low,snapshot.car_high,rfg,tune,&next.charge_uah)) {
        transport.fault=1;transport_fault=1;errors++;goto done;
    }
    samples++;raw_current=snapshot.current;
    if(have_ticks && snapshot.ticks!=last_ticks && !mt6762_gauge_progress(last_ticks,snapshot.ticks)) {
        transport.fault=1;transport_fault=1;errors++;goto done;
    }
    if(have_ticks && mt6762_gauge_progress(last_ticks,snapshot.ticks)) {
        clock_get_uptime(&now);
        if(now>=next.acquired_abs && now<next.expires_abs) {observation=next;valid=1;}
        else freshness_rejections++;
    } else if(have_ticks)freshness_rejections++;
    last_ticks=snapshot.ticks;have_ticks=1;
done:
    lck_mtx_unlock(&gauge_mutex);
}
#ifndef MT6762_GAUGE_HOST_TEST
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
    printf("MT6762 gauge: coherent calibrated current/signed Coulomb observer; awaiting NTER progression, SOC unavailable\n");
    if(kernel_thread_start(worker,NULL,&thread)==KERN_SUCCESS)thread_deallocate(thread);
    return;
rejected:
    errors++;transport_fault=1;
    printf("MT6762 gauge: missing or mismatched live calibration handoff rejected\n");
}
#endif
