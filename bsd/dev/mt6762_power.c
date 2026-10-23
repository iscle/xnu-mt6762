/* MT6762/MT6357 board power observation and owned charger quiescence.
 * No charging-enable or rail writes.
 * Evidence: tools/mt6762/hardware/power. All native access needs a versioned
 * loader handoff; device readiness and identity are checked independently. */
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <sys/errno.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_power.h>
#include <sys/mt6762_gauge.h>
#include <sys/redwood_input.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include "mt6762_power_protocol.h"
#include "mt6762_charger_protocol.h"
#include "mt6762_thermal_protocol.h"

static LCK_GRP_DECLARE(power_lck_group,"mt6762-power");
static LCK_MTX_DECLARE(pwrap_mutex,&power_lck_group);
static LCK_MTX_DECLARE(adc_mutex,&power_lck_group);
static volatile uint8_t *pwrap, *keypad;
static int pwrap_ready, pwrap_fault, adc_ready, charger_ready, started;
static int pmic_id=-1, power_valid, power_errors, charger_state=-1;
static int charger_owned, charger_lab, charger_control_safe=-1, charger_control=-1;
static int adc_voltage_requests, adc_ntc_requests, adc_voltage_samples, adc_ntc_samples;
static int adc_voltage_min=-1,adc_voltage_max=-1,adc_ntc_min=-1,adc_ntc_max=-1;
static int battery_adc_mv=-1, ntc_adc_mv=-1, ntc_nominal_deci_c=-2730;
static struct mt6762_key_filter key_filter[3];
static struct mt6762_bif_transport bif_transport;
static int bif_ready,bif_raw=-1,bif_ntc_raw=-1,bif_samples,bif_errors,bif_fault;
static int bif_generation_rejections,bif_last_error;
static uint64_t bif_deadline;
static const uint16_t bif_config_regs[]={0x10de,0x10e0,0x1120,0x1126,0x1128,
    0x112e,0x1132,0x1136,0x113a,0x113c};
static uint16_t bif_config[10];

SYSCTL_DECL(_kern_redwood);
static int bif_sysctl SYSCTL_HANDLER_ARGS
{
    uint64_t now;
    int value;
    lck_mtx_lock(&adc_mutex);
    clock_get_uptime(&now);
    int fresh=bif_deadline && now<bif_deadline && !bif_transport.fault;
    value=arg2==2?fresh:(fresh?(arg2?bif_ntc_raw:bif_raw):-1);
    lck_mtx_unlock(&adc_mutex);
    return sysctl_handle_int(oidp,&value,0,req);
}
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_bif_raw,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,bif_sysctl,"I","Fresh paired BIF raw ADC count; -1 invalid, not calibrated voltage");
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_bif_ntc_raw,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,1,bif_sysctl,"I","Fresh paired NTC raw ADC count; -1 invalid, not temperature");
SYSCTL_PROC(_kern_redwood,OID_AUTO,mt6762_bif_pair_fresh,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,2,bif_sysctl,"I","Fresh paired samples with unchanged configuration and TDET");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_bif_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_samples,0,"Completed diagnostic NTC/BIF pairs");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_bif_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_errors,0,"BIF admission or sampling failures");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_bif_fault,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_fault,0,"Sticky diagnostic BIF ownership/configuration failure");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_bif_generation_rejections,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_generation_rejections,0,"Invalid missed-generation pairs eligible for next-period retry");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_bif_last_error,CTLFLAG_RD|CTLFLAG_LOCKED,&bif_last_error,0,"Last BIF result: 0 completed, -5 missed generation; other negatives are errors");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_pmic_id,CTLFLAG_RD|CTLFLAG_LOCKED,&pmic_id,0,"Observed MT6357 hardware ID, -1 unknown");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_power_valid,CTLFLAG_RD|CTLFLAG_LOCKED,&power_valid,0,"Current native battery sample validity mask");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_power_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&power_errors,0,"Native power read failures");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_charger_state,CTLFLAG_RD|CTLFLAG_LOCKED,&charger_state,0,"PSC5425E raw state 0..3, -1 unknown");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_battery_adc_mv,CTLFLAG_RD|CTLFLAG_LOCKED,&battery_adc_mv,0,"MT6357 battery ADC millivolts, -1 unknown");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_ntc_adc_mv,CTLFLAG_RD|CTLFLAG_LOCKED,&ntc_adc_mv,0,"MT6357 thermistor ADC millivolts, -1 unknown");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_ntc_nominal_deci_c,CTLFLAG_RD|CTLFLAG_LOCKED,&ntc_nominal_deci_c,0,"Uncalibrated NTC estimate, never used to enable charging; -2730 unknown");

SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_charger_control_safe,CTLFLAG_RD|CTLFLAG_LOCKED,&charger_control_safe,0,"CE readback disabled: 1; rejected 0; unknown -1. No independent fallback guarantee");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_voltage_requests,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_requests,0,"Successful battery-voltage ADC request transactions");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_ntc_requests,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_requests,0,"Successful NTC ADC request transactions");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_voltage_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_samples,0,"Valid voltage conversions");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_ntc_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_samples,0,"Valid NTC conversions, not calibrated temperature");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_voltage_min,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_min,0,"Minimum observed battery ADC mV, -1 none");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_voltage_max,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_max,0,"Maximum observed battery ADC mV, -1 none");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_ntc_min,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_min,0,"Minimum observed NTC ADC mV, -1 none");
SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_adc_ntc_max,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_max,0,"Maximum observed NTC ADC mV, -1 none");

int mt6762_charger_control_safe(void) {return charger_control_safe==1;}

SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_charger_control,CTLFLAG_RD|CTLFLAG_LOCKED,&charger_control,0,"Last verified disabled PSC control byte; -1 unknown");

static int verified(const char *name)
{
    uint32_t value=0;
    return !mt6762_handoff_u32(name,&value) && value==1;
}
static uint32_t pwrap_rd(void *unused,uint32_t offset)
{
    uint32_t v;
    (void)unused;
    v=*(volatile uint32_t *)(pwrap+offset);
    __asm__ volatile("dmb oshld" ::: "memory");
    return v;
}
static void pwrap_wr(void *unused,uint32_t offset,uint32_t value)
{
    (void)unused;
    __asm__ volatile("dmb oshst" ::: "memory");
    *(volatile uint32_t *)(pwrap+offset)=value;
    __asm__ volatile("dsb sy" ::: "memory");
}
static void pwrap_delay(void *unused,unsigned us) {(void)unused;delay(us);}
static const struct mt6762_wacs_io pwrap_io={NULL,pwrap_rd,pwrap_wr,pwrap_delay};

static int pwrap_transfer(int write,uint16_t address,uint16_t *value)
{
    int e;
    if(!value || (address&1))return -EINVAL;
    lck_mtx_lock(&pwrap_mutex);
    if(!pwrap_ready || pwrap_fault) {lck_mtx_unlock(&pwrap_mutex);return -ENXIO;}
    e=mt6762_wacs_transfer(&pwrap_io,write,address,value);
    /* A timed out or uninitialized wrapper needs ownership-aware recovery.
     * Do not blindly clear a transaction belonging to another processor. */
    if(e)pwrap_fault=1;
    lck_mtx_unlock(&pwrap_mutex);
    return e ? (e==-3 ? -ETIMEDOUT : -EIO) : 0;
}
int mt6762_pwrap_read16(uint16_t address,uint16_t *value)
{
    return pwrap_transfer(0,address,value);
}
int mt6762_pwrap_write16(uint16_t address,uint16_t value)
{
    return pwrap_transfer(1,address,&value);
}

/* The handoff grants exclusive AP ownership of initialized ADC channels.
 * BIF additionally requires an already-clear TDET bit. Native code has no
 * independent fallback capable of restoring TDET after losing PWRAP. */
static int adc_rd(void *unused,uint16_t address,uint16_t *v)
{(void)unused;return mt6762_pwrap_read16(address,v);}
static int adc_wr(void *unused,uint16_t address,uint16_t v)
{
    int e;
    (void)unused;e=mt6762_pwrap_write16(address,v);
    if(!e && address==0x110e) {
        if(v==2)adc_voltage_requests++;
        if(v==8)adc_ntc_requests++;
    }
    return e;
}
static const struct mt6762_adc_io adc_io={NULL,adc_rd,adc_wr,pwrap_delay};
static int bif_wr(void *unused,uint16_t address,uint16_t value)
{
    /* A second enforcement boundary: no native BIF path can write TDET. */
    if(address!=0x110e || (value!=8 && value!=2048))return -EPERM;
    return adc_wr(unused,address,value);
}
static int bif_config_matches(void)
{
    uint16_t word;
    if(mt6762_pwrap_read16(8,&word) || (word>>8)!=0x57)return 0;
    for(unsigned i=0;i<10;i++)
        if(mt6762_pwrap_read16(bif_config_regs[i],&word) || word!=bif_config[i])return 0;
    return 1;
}
static void bif_init(void)
{
    static const char *names[]={"bif-sw-gain-trim","bif-sw-offset-trim",
        "bif-adc-con0","bif-adc-con1","bif-adc-con2","bif-adc-con5",
        "bif-adc-con7","bif-adc-con9","bif-adc-con11","bif-adc-con12"};
    uint32_t word;
    uint16_t observed;
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
    if(!bif_config_matches() || mt6762_pwrap_read16(0x1236,&observed) ||
       observed!=bif_transport.expected_tdet)goto rejected;
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
    uint64_t expires,now;
    int e=-EIO;
    lck_mtx_lock(&adc_mutex);
    bif_deadline=0;
    if(bif_transport.fault)goto out;
    clock_interval_to_deadline(2000,NSEC_PER_MSEC,&expires);
    if(!bif_config_matches()) {e=-6;goto fault;}
    e=mt6762_bif_capture(&bif_transport,&pair);
    /* Always recheck configuration, including when no sample is admissible. */
    if(!bif_config_matches()) {e=-6;goto fault;}
    if(e==-5) {
        int retry=mt6762_bif_retry_generation(&bif_transport,e,1);
        if(retry==1) {
            bif_last_error=e;bif_errors++;bif_generation_rejections++;goto out;
        }
        if(retry<0)e=retry;
    }
    if(e)goto fault;
    clock_get_uptime(&now);
    if(now>=expires) {e=-3;goto fault;}
    bif_ntc_raw=pair.ntc_raw;bif_raw=pair.bif_raw;bif_samples++;
    *ntc_mv=(int)((uint32_t)pair.ntc_raw*1800/4096);
    bif_deadline=expires;
    bif_last_error=0;e=0;
    goto out;
fault:
    bif_transport.fault=1;bif_fault=1;bif_errors++;bif_last_error=e;
out:
    lck_mtx_unlock(&adc_mutex);return e;
}
int mt6762_pmic_thermal_sample(unsigned sensor,uint16_t *raw)
{
    static const struct mt6762_thermal_adc_io io={NULL,adc_rd,adc_wr,pwrap_delay};
    int e;
    if(!adc_ready || !verified("pmic-thermal-adc-owned"))return -ENXIO;
    lck_mtx_lock(&adc_mutex);
    e=mt6762_thermal_adc(&io,sensor,raw);
    lck_mtx_unlock(&adc_mutex);
    return e;
}
static int adc_read(unsigned channel,int *mv)
{
    int e;
    if(!adc_ready)return -ENXIO;
    lck_mtx_lock(&adc_mutex);
    e=mt6762_adc_sample(&adc_io,channel,mv);
    lck_mtx_unlock(&adc_mutex);
    return e;
}
static int nominal_ntc(int adc_mv)
{
    static const uint32_t r[]={195652,148171,113347,87559,68237,53650,
        42506,33892,27219,22021,17926,14674,12081,10000,8315,6948,5834,
        4917,4161,3535,3014};
    uint64_t resistance;
    if(adc_mv<=0 || adc_mv>=1800)return -2730;
    resistance=(uint64_t)(unsigned)adc_mv*16900/(1800-(unsigned)adc_mv);
    if(resistance>r[0] || resistance<r[20])return -2730;
    for(unsigned i=1;i<21;i++)if(resistance>=r[i]) {
        int cold=-400+50*((int)i-1),warm=cold+50;
        return (int)(((int64_t)(resistance-r[i])*cold+
            (int64_t)(r[i-1]-resistance)*warm)/(r[i-1]-r[i]));
    }
    return -2730;
}
static int charger_read(uint8_t address,uint8_t *value)
{
    return mt6762_i2c_transfer(5,0x6a,&address,1,value,1);
}
static int psc_rd(void *unused,uint8_t address,uint8_t *value)
{(void)unused;return charger_read(address,value);}
static int psc_wr(void *unused,uint8_t address,uint8_t value)
{
    uint8_t bytes[]={address,value};
    (void)unused;
    return mt6762_i2c_transfer(5,0x6a,bytes,2,NULL,0);
}
static const struct mt6762_psc_io psc_io={NULL,psc_rd,psc_wr};
static void adc_observed(int value,int *count,int *minimum,int *maximum)
{
    (*count)++;
    if(*minimum<0 || value<*minimum)*minimum=value;
    if(*maximum<0 || value>*maximum)*maximum=value;
}
static void button_sample(unsigned which,int valid,unsigned pressed)
{
    static const uint32_t ids[]={REDWOOD_BUTTON_LOCK,REDWOOD_BUTTON_VOLUME_UP,
                                REDWOOD_BUTTON_VOLUME_DOWN};
    int change=mt6762_key_update(&key_filter[which],valid,pressed);
    if(change)redwood_touch_post(change>0?REDWOOD_BUTTON_DOWN:REDWOOD_BUTTON_UP,
                               ids[which],0,0);
}
static void poll_buttons(void)
{
    uint16_t status=0;
    int valid=pwrap_ready && !mt6762_pwrap_read16(0x24,&status);
    button_sample(0,valid,!(status&2));
    if(keypad) {
        uint16_t enabled=*(volatile uint16_t *)(keypad+0x24);
        uint16_t matrix=*(volatile uint16_t *)(keypad+4);
        __asm__ volatile("dmb oshld" ::: "memory");
        button_sample(1,!!(enabled&1),!(matrix&2));
        button_sample(2,!!(enabled&1),!(matrix&1));
    }
}
static void poll_battery(void)
{
    struct mt6762_battery_sample s={.size=sizeof(s)};
    uint16_t v;
    uint8_t id,state;
    static uint32_t last_valid=~0u;
    static int last_charger=-2,last_safe=-2;
    battery_adc_mv=ntc_adc_mv=-1;
    ntc_nominal_deci_c=-2730;
    charger_state=-1;
    if(pwrap_ready && !mt6762_pwrap_read16(0x24,&v)) {
        s.external=!!(v&4);s.valid|=MT6762_BAT_EXTERNAL;
    }else if(pwrap_ready)power_errors++;
    if(pwrap_ready && !mt6762_pwrap_read16(0xe08,&v) && (v&1)) {
        s.present=!(v&2);s.valid|=MT6762_BAT_PRESENT;
    }
    if(adc_ready) {
        if(!adc_read(1,&battery_adc_mv)) {
            adc_observed(battery_adc_mv,&adc_voltage_samples,&adc_voltage_min,&adc_voltage_max);
            s.voltage_uv=battery_adc_mv*1000;s.valid|=MT6762_BAT_VOLTAGE;
        }else power_errors++;
        if(!(bif_ready?bif_read(&ntc_adc_mv):adc_read(3,&ntc_adc_mv))) {
            adc_observed(ntc_adc_mv,&adc_ntc_samples,&adc_ntc_min,&adc_ntc_max);
            ntc_nominal_deci_c=nominal_ntc(ntc_adc_mv);
        }
        else power_errors++;
    }
    if(charger_ready) {
        uint8_t control;
        int safe=charger_owned ? !mt6762_psc_disable_owned(&psc_io,1,&control) : 0;
        charger_control_safe=charger_owned ? (safe?1:-1) : -1;
        charger_control=safe?control:-1;
        if((safe || (charger_lab && !charger_owned)) &&
           !charger_read(3,&id) && id==0xf0 && !charger_read(0,&state)) {
            static const int status_map[]={3,1,4};
            charger_state=(state>>4)&3;
            /* Datasheet reserves state 3; stock maps it to not-charging.
             * Treat it as unknown, and reject a disabled/charging conflict. */
            if(charger_state<3 && !(safe && charger_state==1)) {
                s.status=status_map[charger_state];s.valid|=MT6762_BAT_STATUS;
            }
            if(safe && charger_state==1)charger_control_safe=-1;
        }else {power_errors++;if(charger_owned)charger_control_safe=-1;}
    }
    if(!mt6762_gauge_current_read(&s.current_ua))s.valid|=MT6762_BAT_CURRENT;
    /* Learned SOC and compensated battery NTC are not established. Their
     * validity bits remain clear; no fake percentage or25C value. */
    power_valid=(int)s.valid;
    if(s.valid!=last_valid || charger_state!=last_charger || charger_control_safe!=last_safe) {
        printf("MT6762 power: observed valid=%#x PSC state=%d CE-safe=%d control=%d battery ADC=%d mV\n",
            s.valid,charger_state,charger_control_safe,charger_control,battery_adc_mv);
        last_valid=s.valid;last_charger=charger_state;last_safe=charger_control_safe;
    }
    mt6762_battery_report(&s);
}
static void power_thread(__unused void *parameter,__unused wait_result_t result)
{
    for(unsigned tick=0;;tick++) {
        poll_buttons();
        if(tick%60==0)poll_battery();
        delay_for_interval(16,NSEC_PER_MSEC);
    }
}
void mt6762_power_init(void)
{
    uint16_t id;
    thread_t thread;
    if(started || !mt6762_platform_ready())return;
    if(verified("pwrap-verified")) {
        pwrap=mt6762_map_mmio(0x1000d000,0x1000);
        if(pwrap) {
            pwrap_ready=1;
            if(mt6762_pwrap_read16(8,&id) || (id>>8)!=0x57) {
                pwrap_ready=0;
                printf("MT6762 power: PMIC identification failed; PWRAP observations disabled\n");
            }else pmic_id=id;
        }
    }
    adc_ready=pwrap_ready && verified("adc-verified");
    bif_init();
    charger_owned=verified("charger-control-owned");
    charger_lab=verified("lab-fixture");
    charger_ready=verified("charger-verified") && mt6762_i2c_ready(5);
    if(charger_ready && !charger_owned && !charger_lab) {
        charger_ready=0;charger_control_safe=0;
        printf("MT6762 power: rejected charger handoff without control ownership\n");
    }
    if(charger_ready && charger_owned) {
        uint8_t control;
        charger_control_safe=mt6762_psc_disable_owned(&psc_io,1,&control)?-1:1;
        charger_control=charger_control_safe==1?control:-1;
        if(charger_control_safe!=1)
            printf("MT6762 power: charger disable/readback failed; safety unknown\n");
    }
    if(verified("keypad-verified"))keypad=mt6762_map_mmio(0x10010000,0x1000);
    if(!pwrap_ready && !charger_ready && !keypad)return;
    if(kernel_thread_start(power_thread,NULL,&thread)==KERN_SUCCESS) {
        started=1;thread_deallocate(thread);
        printf("MT6762 power: PMIC %#x; buttons/power observation, ADC=%d charger=%d; charging policy unavailable\n",pmic_id,adc_ready,charger_ready);
    }
}
