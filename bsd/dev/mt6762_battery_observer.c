/* Included by mt6762_power.c. Inherited hardware observation, not a charging
 * controller: no CE, limit, calibration, TDET or rail writes. Separate optional
 * gauge/voltage capabilities admit only their exact latch/request sequence. */
#include "../../tools/mt6762/hardware/power/mt6762_vbat_profile.h"
static struct {
    unsigned started,active,fault,gauge,gauge_fault,samples,gauge_samples,have_ticks;
    unsigned vbat,vbat_fault,vbat_samples;
    uint64_t next,last_start,last_ticks,acquired,expires;
    int current;
    int64_t charge;
    struct gauge_latch_context *gauge_context;
    struct vbat_observer_context *vbat_context;
    uint16_t vbat_entry[MT6762_VBAT_ENTRY_COUNT];
    struct mt6762_gauge_probe_profile profile;
} battery_observer;
struct battery_observer_lease {uint64_t start,end;};

static int battery_observer_lease_ok(const struct battery_observer_lease *lease)
{
    uint64_t now;
    clock_get_uptime(&now);
    return mt6762_gauge_probe_in_lease(lease->start,lease->end,now);
}
static int battery_observer_pmic(struct battery_observer_lease *lease,uint16_t reg,uint16_t *value)
{
    if(!battery_observer_lease_ok(lease))return -ETIMEDOUT;
    int error=mt6762_pwrap_read16(reg,value);
    return error?error:battery_observer_lease_ok(lease)?0:-ETIMEDOUT;
}
static int battery_observer_psc_read(void *context,uint8_t reg,uint8_t *value)
{
    struct battery_observer_lease *lease=context;
    if(!battery_observer_lease_ok(lease))return -ETIMEDOUT;
    int error=charger_read(reg,value);
    return error?error:battery_observer_lease_ok(lease)?0:-ETIMEDOUT;
}
/* The finite-probe policy is reused only for its first sample. An observer
 * callback cannot arm sample1, admit a fifth write, or renew this lease. */
static int battery_observer_gauge_read(void *context,uint16_t reg,uint16_t *value)
{
    struct gauge_latch_context *ctx=context;
    if(!ctx)return -EINVAL;
    if(!battery_observer.active || !battery_observer.gauge || battery_observer.fault ||
       ctx!=battery_observer.gauge_context || ctx->budget.next_sample || battery_observer.gauge_fault)
        return mt6762_gauge_probe_reject(&ctx->budget),-EPERM;
    return gauge_latch_read(ctx,reg,value);
}
static int battery_observer_gauge_write(void *context,uint16_t reg,uint16_t value)
{
    struct gauge_latch_context *ctx=context;
    if(!ctx)return -EINVAL;
    if(!battery_observer.active || !battery_observer.gauge || battery_observer.fault ||
       ctx!=battery_observer.gauge_context || ctx->budget.next_sample ||
       ctx->budget.attempted>=4 || battery_observer.gauge_fault)
        return mt6762_gauge_probe_reject(&ctx->budget),-EPERM;
    return gauge_latch_write(ctx,reg,value);
}
static int battery_observer_gauge_config(struct gauge_latch_context *ctx,const char *phase)
{
    for(unsigned i=0;i<8;i++) {
        uint16_t value=0;
        int error=battery_observer_gauge_read(ctx,mt6762_gauge_probe_entry_regs[i],&value);
        if(error || value!=mt6762_gauge_probe_entry_values[i]) {
            kprintf("MT6762_GAUGE_OBSERVER_CONFIG phase=%s address=%04x value=%04x expected=%04x error=%d\n",
                phase,mt6762_gauge_probe_entry_regs[i],value,mt6762_gauge_probe_entry_values[i],error);
            mt6762_gauge_probe_reject(&ctx->budget);
            return error?error:-EINVAL;
        }
    }
    return 0;
}
static int battery_observer_gauge_sample(struct battery_observer_lease *lease,
    struct mt6762_battery_sample *sample)
{
    struct gauge_latch_context ctx={.acquired=lease->start,.deadline=lease->end};
    struct mt6762_gauge_transport io={.io={&ctx,battery_observer_gauge_read,
        battery_observer_gauge_write,gauge_latch_delay}};
    struct mt6762_gauge_snapshot raw;
    int error=-EPERM,current=0;
    int64_t charge=0;
    battery_observer.expires=0;
    battery_observer.gauge_context=&ctx;
    if(!mt6762_gauge_probe_begin(&ctx.budget,0))goto failed;
    error=battery_observer_gauge_config(&ctx,"before");if(error)goto failed;
    error=-EPERM;if(!mt6762_gauge_probe_arm(&ctx.budget))goto failed;
    error=mt6762_gauge_capture(&io,&raw);if(error)goto failed;
    error=battery_observer_gauge_config(&ctx,"after");if(error)goto failed;
    error=-ETIMEDOUT;if(!battery_observer_lease_ok(lease))goto failed;
    error=-EINVAL;
    if(mt6762_gauge_current(raw.current,battery_observer.profile.rfg,battery_observer.profile.tune,&current) ||
       mt6762_gauge_charge(raw.car_low,raw.car_high,battery_observer.profile.rfg,battery_observer.profile.tune,&charge))goto failed;
    error=-EPERM;if(!mt6762_gauge_probe_finish(&ctx.budget))goto failed;
    error=-ESTALE;
    if(battery_observer.have_ticks && !mt6762_gauge_progress(battery_observer.last_ticks,raw.ticks))goto failed;
    battery_observer.gauge_samples++;
    if(battery_observer.have_ticks) {
        battery_observer.current=current;battery_observer.charge=charge;
        battery_observer.acquired=lease->start;battery_observer.expires=lease->end;
        sample->current_ua=current;sample->valid|=MT6762_BAT_CURRENT;
    }
    kprintf("MT6762_GAUGE_OBSERVER sample=%u raw_current=%04x car_low=%04x car_high=%04x nter=%llx current_ua=%d signed_charge_uah=%lld fresh=%u writes=%u acquired=%llx expires=%llx soc_valid=0 absolute_calibration=0\n",
        battery_observer.gauge_samples,raw.current,raw.car_low,raw.car_high,
        (unsigned long long)raw.ticks,current,(long long)charge,battery_observer.have_ticks,
        ctx.budget.attempted,(unsigned long long)lease->start,(unsigned long long)lease->end);
    battery_observer.last_ticks=raw.ticks;battery_observer.have_ticks=1;
    battery_observer.gauge_context=NULL;
    return 0;
failed:
    battery_observer.gauge_fault=1;battery_observer.expires=0;
    battery_observer.gauge_context=NULL;
    mt6762_gauge_probe_reject(&ctx.budget);
    kprintf("MT6762_GAUGE_OBSERVER_STOP error=%d writes_attempted=%u writes_completed=%u latch_idle_observed=%u cleanup_writes=0\n",
        error,ctx.budget.attempted,ctx.budget.completed,ctx.latch_idle_observed);
    return error;
}

/* C-only bridge for existing gauge sysctls; no ABI/header change. -ENXIO means
 * this path was not selected; active but unmeasured/expired is -EAGAIN. */
int mt6762_inherited_gauge_snapshot(int *current,int64_t *charge,uint64_t *acquired,uint64_t *expires)
{
    uint64_t now;
    int error=-ENXIO;
    if(!current || !charge || !acquired || !expires)return -EINVAL;
    lck_mtx_lock(&battery_observer_mutex);
    if(battery_observer.active && battery_observer.gauge) {
        error=-EAGAIN;clock_get_uptime(&now);
        if(!battery_observer.fault && !battery_observer.gauge_fault &&
           mt6762_gauge_probe_in_lease(battery_observer.acquired,battery_observer.expires,now)) {
            *current=battery_observer.current;*charge=battery_observer.charge;
            *acquired=battery_observer.acquired;
            *expires=battery_observer.expires;error=0;
        }
    }
    lck_mtx_unlock(&battery_observer_mutex);
    return error;
}

#include "mt6762_vbat_observer.c"

static void battery_inherited_poll(void)
{
    struct mt6762_battery_sample sample={.size=sizeof(sample)};
    struct mt6762_psc_observation psc={0};
    struct battery_observer_lease lease;
    struct mt6762_psc_io io={&lease,battery_observer_psc_read,NULL};
    uint16_t id=0,external=0,present=0;
    uint64_t interval,now;
    int error=-EINVAL;
    const char *stage="lease";
    lck_mtx_lock(&battery_observer_mutex);
    if(!battery_observer.active || battery_observer.fault)goto inactive;
    clock_get_uptime(&lease.start);
    if(lease.start<battery_observer.last_start)goto failed;
    if(lease.start<battery_observer.next)goto inactive;
    battery_observer.last_start=lease.start;
    clock_interval_to_absolutetime_interval(2000,NSEC_PER_MSEC,&interval);
    if(!mt6762_gauge_probe_deadline(lease.start,interval,&lease.end))goto failed;
    sample.acquired_abs=lease.start;sample.expires_abs=lease.end;
    stage="wrapper";error=-ENXIO;
    if(!gauge_latch_wrapper_ok() || !mt6762_i2c_ready(5))goto failed;
    stage="pmic-id";error=battery_observer_pmic(&lease,8,&id);if(error)goto failed;
    error=-ENODEV;if(id!=0x5730)goto failed;
    stage="external";error=battery_observer_pmic(&lease,0x24,&external);if(error)goto failed;
    stage="present";error=battery_observer_pmic(&lease,0xe08,&present);if(error)goto failed;
    sample.external=!!(external&4);sample.valid|=MT6762_BAT_EXTERNAL;
    if(present&1) {sample.present=!(present&2);sample.valid|=MT6762_BAT_PRESENT;}
    stage="psc";error=mt6762_psc_observe(&io,&psc);if(error)goto failed;
    charger_state=(psc.status>>4)&3;
    /* STAT is charger state, not measured current. Reject reserved/fault/OTG
     * and contradictory charging state, while retaining independently valid
     * PMIC presence. Neither CE state confers charging-control ownership. */
    if(!(psc.control&1) && !(psc.status&0x0f) && charger_state<3 &&
       !(charger_state==1 && ((psc.control&6) || !sample.external ||
          !(sample.valid&MT6762_BAT_PRESENT) || !sample.present))) {
        static const int map[]={3,1,4};
        sample.status=map[charger_state];sample.valid|=MT6762_BAT_STATUS;
    }
    if(battery_observer.gauge && !battery_observer.gauge_fault)
        (void)battery_observer_gauge_sample(&lease,&sample);
    if(battery_observer.vbat && !battery_observer.vbat_fault)
        (void)vbat_observer_sample(&lease,&sample);
    stage="completion";error=-ETIMEDOUT;
    if(pwrap_fault || !battery_observer_lease_ok(&lease))goto failed;
    clock_get_uptime(&now);
    clock_interval_to_absolutetime_interval(1000,NSEC_PER_MSEC,&interval);
    if(!mt6762_gauge_probe_deadline(now,interval,&battery_observer.next))goto failed;
    battery_observer.samples++;power_valid=(int)sample.valid;
    kprintf("MT6762_BATTERY_OBSERVER sample=%u valid=%x pmic=%04x external=%d present=%d psc_id=%02x control=%02x status=%02x current_ua=%d soc_valid=0 acquired=%llx expires=%llx\n",
        battery_observer.samples,sample.valid,id,sample.external,sample.present,
        psc.id,psc.control,psc.status,(sample.valid&MT6762_BAT_CURRENT)?sample.current_ua:(-2147483647-1),
        (unsigned long long)sample.acquired_abs,(unsigned long long)sample.expires_abs);
    lck_mtx_unlock(&battery_observer_mutex);
    mt6762_battery_report(&sample);
    return;
failed:
    battery_observer.fault=1;battery_observer.expires=0;power_valid=0;power_errors++;
    sample.valid=0;
    kprintf("MT6762_BATTERY_OBSERVER_STOP stage=%s error=%d samples=%u\n",stage,error,battery_observer.samples);
    lck_mtx_unlock(&battery_observer_mutex);
    mt6762_battery_report(&sample);
    return;
inactive:
    lck_mtx_unlock(&battery_observer_mutex);
}
static int battery_inherited_admit(void)
{
    static const char *conflicts[]={"fgauge-owned","fgauge-calibration-verified","adc-verified",
        "charger-verified","charger-control-owned","pwrap-write-owned","lab-fixture",
        "fgauge-latch-probe","charger-readonly-probe","charger-setup-only"};
    if(!verified("battery-inherited-observer") || battery_observer.started)return 0;
    battery_observer.started=1;
    for(unsigned i=0;i<sizeof(conflicts)/sizeof(conflicts[0]);i++)if(verified(conflicts[i]))return 0;
    if(!verified("pwrap-inherited-probe") || !gauge_latch_wrapper_ok() || !mt6762_i2c_ready(5))return 0;
    battery_observer.gauge=verified("fgauge-inherited-observer");
    if(battery_observer.gauge && !gauge_latch_handoff(&battery_observer.profile))return 0;
    battery_observer.vbat=verified("vbat-inherited-observer");
    if(battery_observer.vbat && !vbat_observer_handoff())return 0;
    battery_observer.active=1;
    return 1;
}
#ifndef MT6762_BATTERY_OBSERVER_HOST_TEST
static void battery_inherited_worker(__unused void *parameter,__unused wait_result_t result)
{
    for(;;) {battery_inherited_poll();delay_for_interval(1000,NSEC_PER_MSEC);}
}
static void battery_inherited_start(void)
{
    thread_t thread;
    if(!battery_inherited_admit()) {
        kprintf("MT6762_BATTERY_OBSERVER_REFUSED handoff_or_wrapper=1\n");return;
    }
    if(kernel_thread_start(battery_inherited_worker,NULL,&thread)!=KERN_SUCCESS) {
        battery_observer.fault=1;kprintf("MT6762_BATTERY_OBSERVER_REFUSED thread_start=1\n");return;
    }
    thread_deallocate(thread);
    kprintf("MT6762_BATTERY_OBSERVER_READY readonly_charger=1 interval_ms=1000 expiry_ms=2000\n");
    if(battery_observer.gauge)kprintf("MT6762_GAUGE_OBSERVER_READY max_writes_per_sample=4\n");
    if(battery_observer.vbat)kprintf("MT6762_VBAT_OBSERVER_READY channel=1 max_requests_per_sample=1\n");
}
#endif
