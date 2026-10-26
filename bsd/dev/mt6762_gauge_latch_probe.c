/* Included by mt6762_power.c. Two physical diagnostic captures; no battery
 * publication, normal gauge worker, ADC requests or charger/rail control. */
#include "mt6762_gauge_protocol.h"
#include "../../tools/mt6762/hardware/power/mt6762_gauge_probe.h"
static LCK_MTX_DECLARE(gauge_latch_mutex,&power_lck_group);
static unsigned gauge_latch_started;
struct gauge_latch_context {
    struct mt6762_gauge_probe_budget budget;
    uint64_t acquired,deadline;
    unsigned reads,latch_idle_observed;
    uint16_t last_address,last_value;
    int last_error,last_write;
};
static int gauge_latch_wrapper_ok(void)
{
    return pwrap_ready && !pwrap_fault && pwrap_read_only && pwrap_profile==MT6762_WACS_LK22 &&
        !adc_ready && !charger_ready && !charger_owned;
}
static int gauge_latch_transfer(struct gauge_latch_context *ctx,int write,uint16_t reg,uint16_t *value)
{
    uint64_t now;
    int error=-EPERM;
    if(!ctx || !value)return -EINVAL;
    lck_mtx_lock(&pwrap_mutex);
    ctx->last_address=reg;ctx->last_value=write?*value:0;ctx->last_write=write;
    clock_get_uptime(&now);
    if(!gauge_latch_wrapper_ok() || ctx->budget.fault || !ctx->budget.active)goto rejected;
    if(!mt6762_gauge_probe_in_lease(ctx->acquired,ctx->deadline,now)) {
        error=-ETIMEDOUT;goto rejected;
    }
    if(write) {
        if(!mt6762_gauge_probe_write_begin(&ctx->budget,reg,*value))goto rejected;
        ctx->latch_idle_observed=0;
    }else {
        if(!mt6762_gauge_probe_read_allowed(&ctx->budget,reg))goto rejected;
        ctx->reads++;
    }
    /* Private exception to read-only mode: only the phase/budget-approved
     * latch write reaches WACS. Public pwrap_transfer remains read-only. */
    error=mt6762_wacs_transfer_profile(&pwrap_io,pwrap_profile,write,reg,value);
    if(write && !mt6762_gauge_probe_write_end(&ctx->budget,error) && !error)error=-1;
    if(error) {
        ctx->latch_idle_observed=0;pwrap_fault=1;error=error==-3?-ETIMEDOUT:-EIO;
        goto rejected;
    }
    /* A transaction that completed after the lease cannot supply a fresh
     * result or authorize another latch write, even if WACS acknowledged it. */
    clock_get_uptime(&now);
    if(!mt6762_gauge_probe_in_lease(ctx->acquired,ctx->deadline,now)) {
        ctx->latch_idle_observed=0;error=-ETIMEDOUT;goto rejected;
    }
    if(!write && reg==0xd0a)ctx->latch_idle_observed=*value==0;
    ctx->last_value=*value;ctx->last_error=0;
    lck_mtx_unlock(&pwrap_mutex);
    if(write)kprintf("MT6762_GAUGE_LATCH_IO write=1 address=%04x value=%04x error=0 attempted=%u completed=%u\n",
        reg,*value,ctx->budget.attempted,ctx->budget.completed);
    return 0;
rejected:
    mt6762_gauge_probe_reject(&ctx->budget);ctx->last_error=error;
    lck_mtx_unlock(&pwrap_mutex);
    kprintf("MT6762_GAUGE_LATCH_IO write=%d address=%04x value=%04x error=%d attempted=%u completed=%u\n",
        write,reg,ctx->last_value,error,ctx->budget.attempted,ctx->budget.completed);
    return error;
}
static int gauge_latch_read(void *context,uint16_t reg,uint16_t *value)
{return gauge_latch_transfer(context,0,reg,value);}
static int gauge_latch_write(void *context,uint16_t reg,uint16_t value)
{return gauge_latch_transfer(context,1,reg,&value);}
static void gauge_latch_delay(void *context,unsigned us)
{(void)context;pwrap_wacs_delay(NULL,us);}
static int gauge_latch_entry(struct gauge_latch_context *ctx,unsigned sample,const char *phase)
{
    uint16_t words[8];
    for(unsigned i=0;i<8;i++) {
        int error=gauge_latch_read(ctx,mt6762_gauge_probe_entry_regs[i],&words[i]);
        if(error || words[i]!=mt6762_gauge_probe_entry_values[i]) {
            kprintf("MT6762_GAUGE_LATCH_CONFIG_FAILED sample=%u phase=%s index=%u address=%04x value=%04x expected=%04x transport=%d\n",
                sample,phase,i,mt6762_gauge_probe_entry_regs[i],error?0:words[i],
                mt6762_gauge_probe_entry_values[i],error);
            mt6762_gauge_probe_reject(&ctx->budget);return error?error:-EINVAL;
        }
    }
    kprintf("MT6762_GAUGE_LATCH_CONFIG sample=%u phase=%s id=%04x clock=%04x con0=%04x efuse_gain=%04x efuse_offset=%04x adjust=%04x gain=%04x latch=%04x\n",
        sample,phase,words[0],words[1],words[2],words[3],words[4],words[5],words[6],words[7]);
    return 0;
}
static int gauge_latch_handoff(struct mt6762_gauge_probe_profile *profile)
{
    static const char *names[5]={"fgauge-con0","fgauge-efuse-gain","fgauge-efuse-offset","fgauge-adjust-offset","fgauge-gain"};
    static const char *conflicts[]={"fgauge-owned","fgauge-calibration-verified","adc-verified",
        "charger-verified","charger-control-owned","pwrap-write-owned","lab-fixture"};
    for(unsigned i=0;i<sizeof(conflicts)/sizeof(conflicts[0]);i++)if(verified(conflicts[i]))return 0;
    if(!verified("pwrap-inherited-probe") ||
       mt6762_handoff_u32("fgauge-baseline-version",&profile->version) ||
       mt6762_handoff_u32("fgauge-rfg",&profile->rfg) ||
       mt6762_handoff_u32("fgauge-car-tune",&profile->tune))return 0;
    for(unsigned i=0;i<5;i++)if(mt6762_handoff_u32(names[i],&profile->config[i]))return 0;
    return mt6762_gauge_probe_profile_ok(profile);
}
static void gauge_latch_probe(void)
{
    struct mt6762_gauge_probe_profile profile;
    struct gauge_latch_context ctx={0};
    struct mt6762_gauge_transport transport={.io={&ctx,gauge_latch_read,gauge_latch_write,gauge_latch_delay}};
    struct mt6762_gauge_snapshot snapshot;
    uint64_t interval,now,previous_ticks=0,earliest=0;
    unsigned snapshots=0,progress=0;
    int error=-EINVAL,current_ua;
    int64_t charge_uah;
    const char *stage="handoff";
    if(!verified("fgauge-latch-probe"))return;
    lck_mtx_lock(&gauge_latch_mutex);
    if(gauge_latch_started) {lck_mtx_unlock(&gauge_latch_mutex);return;}
    gauge_latch_started=1; /* Includes refusals: never retry in the same boot. */
    if(!gauge_latch_handoff(&profile))goto done;
    lck_mtx_lock(&pwrap_mutex);
    int wrapper_ok=gauge_latch_wrapper_ok();
    lck_mtx_unlock(&pwrap_mutex);
    stage="wrapper";if(!wrapper_ok)goto done;
    for(unsigned sample=0;sample<2;sample++) {
        stage="lease";error=-ETIMEDOUT;clock_get_uptime(&ctx.acquired);
        clock_interval_to_absolutetime_interval(2000,NSEC_PER_MSEC,&interval);
        if(ctx.acquired<earliest ||
           !mt6762_gauge_probe_deadline(ctx.acquired,interval,&ctx.deadline) ||
           !mt6762_gauge_probe_begin(&ctx.budget,sample))goto done;
        stage="before";error=gauge_latch_entry(&ctx,sample,"before");if(error)goto done;
        if(!sample)kprintf("MT6762_GAUGE_LATCH_BEGIN samples=2 max_writes=8\n");
        stage="arm";error=-EPERM;if(!mt6762_gauge_probe_arm(&ctx.budget))goto done;
        stage="latch";error=mt6762_gauge_capture(&transport,&snapshot);if(error)goto done;
        snapshots++;
        kprintf("MT6762_GAUGE_LATCH_RAW sample=%u current=%04x car_low=%04x car_high=%04x nter_low=%04x nter_high=%04x nter_top=%04x nter=%llx measurement_published=0\n",
            sample,snapshot.current,snapshot.car_low,snapshot.car_high,
            (unsigned)(snapshot.ticks&0xffff),(unsigned)((snapshot.ticks>>16)&0xffff),
            (unsigned)(snapshot.ticks>>32),(unsigned long long)snapshot.ticks);
        stage="after";error=gauge_latch_entry(&ctx,sample,"after");if(error)goto done;
        stage="lease";error=-ETIMEDOUT;clock_get_uptime(&now);
        if(!mt6762_gauge_probe_in_lease(ctx.acquired,ctx.deadline,now))goto done;
        stage="coefficient-conversion";error=-EINVAL;
        if(mt6762_gauge_current(snapshot.current,profile.rfg,profile.tune,&current_ua) ||
           mt6762_gauge_charge(snapshot.car_low,snapshot.car_high,profile.rfg,profile.tune,&charge_uah))goto done;
        stage="finish";error=-EPERM;if(!mt6762_gauge_probe_finish(&ctx.budget))goto done;
        if(sample) {
            stage="nter";error=-ESTALE;
            if(!mt6762_gauge_progress(previous_ticks,snapshot.ticks))goto done;
            progress=1;
        }
        kprintf("MT6762_GAUGE_LATCH_SAMPLE sample=%u acquired=%llx completed=%llx expires=%llx rfg=%u car_tune=%u coefficient_current_ua=%d coefficient_charge_uah=%lld nter_progress=%u diagnostic_valid=%u absolute_calibration=0 measurement_published=0\n",
            sample,(unsigned long long)ctx.acquired,(unsigned long long)now,
            (unsigned long long)ctx.deadline,profile.rfg,profile.tune,current_ua,
            (long long)charge_uah,progress,progress);
        if(!sample) {
            previous_ticks=snapshot.ticks;stage="separation";error=-ETIMEDOUT;
            clock_interval_to_absolutetime_interval(1000,NSEC_PER_MSEC,&interval);
            if(!mt6762_gauge_probe_deadline(now,interval,&earliest))goto done;
            delay_for_interval(1000,NSEC_PER_MSEC);
        }
    }
    stage="complete";error=0;
done:
    /* Permanently close this local capability on every exit. It is never a
     * grant to the normal observer or the public PWRAP write API. */
    mt6762_gauge_probe_reject(&ctx.budget);ctx.budget.active=0;ctx.budget.armed=0;
    kprintf("MT6762_GAUGE_LATCH_END stage=%s error=%d samples=%u writes_attempted=%u writes_completed=%u reads=%u nter_progress=%u last_write=%d last_address=%04x last_value=%04x last_error=%d latch_idle_observed=%u cleanup_writes=0 diagnostic_valid=%u absolute_calibration=0 measurement_published=0 ownership_grant=0\n",
        stage,error,snapshots,ctx.budget.attempted,ctx.budget.completed,ctx.reads,progress,
        ctx.last_write,ctx.last_address,ctx.last_value,ctx.last_error,ctx.latch_idle_observed,
        !error && snapshots==2 && progress);
    lck_mtx_unlock(&gauge_latch_mutex);
}
