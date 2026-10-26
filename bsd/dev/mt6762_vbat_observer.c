/* Included by mt6762_battery_observer.c. One exact channel1 conversion, no
 * generic ADC grant, NTC/BIF/TDET, clock/reset, trim or charger writes. */
struct vbat_observer_context {
    struct battery_observer_lease lease;
    unsigned phase,attempted,completed,reads,fault;
};
static int vbat_observer_transfer(struct vbat_observer_context *ctx,int write,uint16_t reg,uint16_t *value)
{
    uint64_t now;
    int error=-EPERM;
    if(!ctx || !value)return -EINVAL;
    lck_mtx_lock(&pwrap_mutex);
    if(!battery_observer.active || !battery_observer.vbat || battery_observer.fault ||
       battery_observer.vbat_fault || ctx!=battery_observer.vbat_context || ctx->fault ||
       !gauge_latch_wrapper_ok())goto rejected;
    clock_get_uptime(&now);
    if(!mt6762_gauge_probe_in_lease(ctx->lease.start,ctx->lease.end,now)) {error=-ETIMEDOUT;goto rejected;}
    if(write) {
        if(ctx->phase!=2 || ctx->attempted || reg!=0x110e || *value!=2)goto rejected;
        ctx->attempted++; /* Includes an ambiguous WACS completion. No retry. */
    }else if(ctx->phase==1 || ctx->phase==3) {
        unsigned index;
        for(index=0;index<MT6762_VBAT_ENTRY_COUNT;index++)if(reg==mt6762_vbat_entry_regs[index])break;
        if(index==MT6762_VBAT_ENTRY_COUNT)goto rejected;
    }else if(ctx->phase!=2 || !ctx->completed || reg!=0x108a)goto rejected;
    error=mt6762_wacs_transfer_profile(&pwrap_io,pwrap_profile,write,reg,value);
    if(error) {pwrap_fault=1;error=error==-3?-ETIMEDOUT:-EIO;goto rejected;}
    if(write) {ctx->completed++;adc_voltage_requests++;}
    else ctx->reads++;
    clock_get_uptime(&now);
    if(!mt6762_gauge_probe_in_lease(ctx->lease.start,ctx->lease.end,now)) {error=-ETIMEDOUT;goto rejected;}
    lck_mtx_unlock(&pwrap_mutex);
    return 0;
rejected:
    ctx->fault=1;
    lck_mtx_unlock(&pwrap_mutex);
    kprintf("MT6762_VBAT_IO write=%d address=%04x error=%d attempted=%u completed=%u\n",
        write,reg,error,ctx->attempted,ctx->completed);
    return error;
}
static int vbat_observer_read(void *context,uint16_t reg,uint16_t *value)
{return vbat_observer_transfer(context,0,reg,value);}
static int vbat_observer_write(void *context,uint16_t reg,uint16_t value)
{return vbat_observer_transfer(context,1,reg,&value);}
static void vbat_observer_delay(void *context,unsigned us)
{
    struct vbat_observer_context *ctx=context;
    if(!battery_observer_lease_ok(&ctx->lease) || (us!=1280 && us!=200)) {ctx->fault=1;return;}
    pwrap_delay(NULL,us);
    if(!battery_observer_lease_ok(&ctx->lease))ctx->fault=1;
}
static int vbat_observer_config(struct vbat_observer_context *ctx,const char *phase)
{
    for(unsigned i=0;i<MT6762_VBAT_ENTRY_COUNT;i++) {
        uint16_t value=0;
        int error=vbat_observer_read(ctx,mt6762_vbat_entry_regs[i],&value);
        if(error || value!=battery_observer.vbat_entry[i]) {
            kprintf("MT6762_VBAT_CONFIG phase=%s address=%04x value=%04x expected=%04x error=%d\n",
                phase,mt6762_vbat_entry_regs[i],value,battery_observer.vbat_entry[i],error);
            ctx->fault=1;return error?error:-EINVAL;
        }
    }
    return 0;
}
static int vbat_observer_sample(const struct battery_observer_lease *lease,struct mt6762_battery_sample *sample)
{
    struct vbat_observer_context ctx={.lease=*lease,.phase=1};
    struct mt6762_battery_adc_io io={&ctx,vbat_observer_read,vbat_observer_write,vbat_observer_delay};
    uint16_t raw=0;
    int error,mv;
    lck_mtx_lock(&adc_mutex);
    battery_adc_mv=-1;battery_observer.vbat_context=&ctx;
    error=vbat_observer_config(&ctx,"before");if(error)goto done;
    ctx.phase=2;
    /* The unchanged protocol requires post-request READY low then high;
     * stale high, missed generation, rails and timeout never publish. */
    error=mt6762_battery_adc_fresh(&io,1,&raw);if(error)goto done;
    ctx.phase=3;
    error=vbat_observer_config(&ctx,"after");if(error)goto done;
    error=-ETIMEDOUT;
    if(ctx.fault || ctx.attempted!=1 || ctx.completed!=1 || !battery_observer_lease_ok(lease))goto done;
    mv=(int)(((uint32_t)raw*3u*1800u)>>15);
    sample->voltage_uv=mv*1000;sample->valid|=MT6762_BAT_VOLTAGE;
    battery_adc_mv=mv;battery_observer.vbat_samples++;
    adc_observed(mv,&adc_voltage_samples,&adc_voltage_min,&adc_voltage_max);
    kprintf("MT6762_VBAT_OBSERVER sample=%u raw=%04x voltage_uv=%d requests=1 acquired=%llx expires=%llx soc_valid=0 absolute_calibration=0\n",
        battery_observer.vbat_samples,raw,sample->voltage_uv,
        (unsigned long long)lease->start,(unsigned long long)lease->end);
    error=0;
done:
    battery_observer.vbat_context=NULL;ctx.phase=0;
    if(error) {
        battery_observer.vbat_fault=1;ctx.fault=1;
        kprintf("MT6762_VBAT_OBSERVER_STOP error=%d requests_attempted=%u requests_completed=%u reads=%u cleanup_writes=0\n",
            error,ctx.attempted,ctx.completed,ctx.reads);
    }
    lck_mtx_unlock(&adc_mutex);
    return error;
}
static int vbat_observer_handoff(void)
{
    static const char *names[]={"vbat-adc-clock0","vbat-adc-clock1","vbat-adc-reset","vbat-adc-test","vbat-adc-reuse"};
    uint32_t value=0;
    if(mt6762_handoff_u32("vbat-adc-profile-version",&value) || value!=MT6762_VBAT_PROFILE_V1)return 0;
    for(unsigned i=0;i<MT6762_VBAT_FIXED_COUNT;i++)battery_observer.vbat_entry[i]=mt6762_vbat_fixed_values[i];
    for(unsigned i=0;i<sizeof(names)/sizeof(names[0]);i++) {
        if(mt6762_handoff_u32(names[i],&value) || value>0xffff)return 0;
        battery_observer.vbat_entry[MT6762_VBAT_FIXED_COUNT+i]=(uint16_t)value;
    }
    return mt6762_vbat_entry_ok(battery_observer.vbat_entry);
}
