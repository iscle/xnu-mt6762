/* Included by mt6762_power.c: owned raw ADC/trim observation, not calibration. */
static struct mt6762_bif_transport bif_transport;
static int bif_ready,bif_raw=-1,bif_ntc_raw=-1,bif_samples,bif_errors,bif_fault;
static int bif_generation_rejections,bif_last_error;
/* Fixed private diagnostic record. Raw trim words never assert calibration.
 * No reset epoch is invented: matching words cannot detect an ABA reset. */
struct mt6762_bif_observation {
    uint32_t version,size;
    uint64_t acquired_abs,expires_abs;
    uint16_t pmic_id,swcid,tdet,ntc_raw,bif_raw;
    uint16_t config[17];
    uint16_t reserved[2];
};
_Static_assert(sizeof(struct mt6762_bif_observation)==72,"BIF diagnostic layout");
static struct mt6762_bif_observation bif_observation;
static const uint16_t bif_config_regs[]={0x10de,0x10e0,0x1120,0x1126,0x1128,
    0x112e,0x1132,0x1136,0x113a,0x113c,
    0x1008,0x11a2,0x11a4,0x11a6,0x11a8,0x11aa,0x11ac};
static uint16_t bif_config[10];
static uint16_t bif_baseline[20]; /* Full HW/SW IDs, TDET, 17 config/trim words. */

static int bif_observation_read(struct mt6762_bif_observation *out)
{
    uint64_t now;
    int e=-ENXIO;
    if(!out)return -EINVAL;
    lck_mtx_lock(&adc_mutex);
    clock_get_uptime(&now);
    if(!bif_transport.fault && bif_observation.expires_abs &&
       now>=bif_observation.acquired_abs && now<bif_observation.expires_abs) {
        *out=bif_observation;e=0;
    }
    lck_mtx_unlock(&adc_mutex);
    return e;
}

#ifndef MT6762_BIF_HOST_TEST
static int bif_sysctl SYSCTL_HANDLER_ARGS
{
    struct mt6762_bif_observation observation;
    int fresh=!bif_observation_read(&observation);
    int value=arg2==2?fresh:(fresh?(arg2?observation.ntc_raw:observation.bif_raw):-1);
    return sysctl_handle_int(oidp,&value,0,req);
}
static int bif_observation_sysctl SYSCTL_HANDLER_ARGS
{
    struct mt6762_bif_observation observation;
    int e;
    (void)arg1;(void)arg2;
    e=bif_observation_read(&observation);
    if(e)return -e;
    return SYSCTL_OUT(req,&observation,sizeof(observation));
}
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_bif_observation,CTLTYPE_OPAQUE|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,bif_observation_sysctl,"S,mt6762_bif_observation","Atomic fresh raw NTC/BIF and trim observation; not calibrated temperature");
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_bif_raw,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,bif_sysctl,"I","Fresh paired BIF raw ADC count; -1 invalid, not calibrated voltage");
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_bif_ntc_raw,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,1,bif_sysctl,"I","Fresh paired NTC raw ADC count; -1 invalid, not temperature");
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_bif_pair_fresh,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,2,bif_sysctl,"I","Fresh paired samples with unchanged configuration and TDET");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_bif_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_samples,0,"Completed diagnostic NTC/BIF pairs");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_bif_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_errors,0,"BIF admission or sampling failures");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_bif_fault,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_fault,0,"Sticky diagnostic BIF ownership/configuration failure");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_bif_generation_rejections,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_generation_rejections,0,"Invalid missed-generation pairs eligible for next-period retry");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_bif_last_error,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_last_error,0,"Last BIF result: 0 completed, -5 missed generation; other negatives are errors");
#endif
static int bif_wr(void *unused,uint16_t address,uint16_t value)
{
    /* A second enforcement boundary: no native BIF path can write TDET. */
    if(address!=0x110e || (value!=8 && value!=2048))return -EPERM;
    return adc_wr(unused,address,value);
}
static int bif_state_read(uint16_t state[20])
{
    if(mt6762_pwrap_read16(8,&state[0]) || (state[0]>>8)!=0x57 ||
       mt6762_pwrap_read16(0xa,&state[1]) ||
       mt6762_pwrap_read16(0x1236,&state[2]) ||
       state[2]!=bif_transport.expected_tdet)return 0;
    for(unsigned i=0;i<17;i++) {
        if(mt6762_pwrap_read16(bif_config_regs[i],&state[i+3]))return 0;
        if(i<10 && state[i+3]!=bif_config[i])return 0;
    }
    return 1;
}
static void bif_init(void)
{
    static const char *names[]={"bif-sw-gain-trim","bif-sw-offset-trim",
        "bif-adc-con0","bif-adc-con1","bif-adc-con2","bif-adc-con5",
        "bif-adc-con7","bif-adc-con9","bif-adc-con11","bif-adc-con12"};
    uint32_t word;
    uint16_t confirmation[20];
    if(!adc_ready || !verified("bif-adc-owned") || !verified("baton-tdet-owned") ||
       !verified("bif-trim-verified"))return;
    if(mt6762_handoff_u32("bif-tdet",&word) || word>0xffff)goto rejected;
    if(word&2) {
        printf("MT6762 BIF: TDET-changing sampling rejected; independent restoration fallback unavailable\n");
        goto rejected;
    }
    bif_transport.expected_tdet=(uint16_t)word;
    for(unsigned i=0;i<10;i++) {
        if(mt6762_handoff_u32(names[i],&word) || word>0xffff)goto rejected;
        bif_config[i]=(uint16_t)word;
    }
    if(!bif_state_read(bif_baseline) || !bif_state_read(confirmation) ||
       memcmp(bif_baseline,confirmation,sizeof(bif_baseline)))goto rejected;
    bif_transport.io=(struct mt6762_battery_adc_io){NULL,adc_rd,bif_wr,pwrap_delay};
    bif_ready=1;
    printf("MT6762 BIF: owned raw-pair diagnostic, TDET remains unchanged; battery temperature unavailable\n");
    return;
rejected:
    bif_errors++;bif_fault=1;bif_transport.fault=1;bif_last_error=-6;
}
static int bif_read(int *ntc_mv)
{
    struct mt6762_bif_pair pair;
    struct mt6762_bif_observation next={.version=1,.size=sizeof(next)};
    uint16_t before[20],after[20];
    uint64_t duration,now;
    int e=-EIO;
    if(!ntc_mv)return -EINVAL;
    lck_mtx_lock(&adc_mutex);
    bif_observation.expires_abs=0;
    if(bif_transport.fault)goto out;
    clock_get_uptime(&next.acquired_abs);
    clock_interval_to_absolutetime_interval(2000,NSEC_PER_MSEC,&duration);
    if(!duration || UINT64_MAX-next.acquired_abs<duration) {e=-3;goto fault;}
    next.expires_abs=next.acquired_abs+duration;
    if(!bif_state_read(before) || memcmp(before,bif_baseline,sizeof(before))) {e=-6;goto fault;}
    e=mt6762_bif_capture(&bif_transport,&pair);
    /* Always recheck configuration, including when no sample is admissible. */
    if(!bif_state_read(after) || memcmp(before,after,sizeof(before))) {e=-6;goto fault;}
    if(e==-5) {
        int retry=mt6762_bif_retry_generation(&bif_transport,e,1);
        if(retry==1) {
            bif_last_error=e;bif_errors++;bif_generation_rejections++;goto out;
        }
        if(retry<0)e=retry;
    }
    if(e)goto fault;
    clock_get_uptime(&now);
    if(now<next.acquired_abs || now>=next.expires_abs) {e=-3;goto fault;}
    next.pmic_id=before[0];next.swcid=before[1];next.tdet=before[2];
    next.ntc_raw=pair.ntc_raw;next.bif_raw=pair.bif_raw;
    memcpy(next.config,before+3,sizeof(next.config));
    bif_ntc_raw=pair.ntc_raw;bif_raw=pair.bif_raw;bif_samples++;
    *ntc_mv=(int)((uint32_t)pair.ntc_raw*1800/4096);
    bif_observation=next;
    bif_last_error=0;e=0;
    goto out;
fault:
    bif_transport.fault=1;bif_fault=1;bif_errors++;bif_last_error=e;
out:
    lck_mtx_unlock(&adc_mutex);return e;
}
