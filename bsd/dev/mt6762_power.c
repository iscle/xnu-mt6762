/* MT6762/MT6357 board power observation and owned charger quiescence.
 * No charging-enable or rail writes.
 * Evidence: tools/mt6762/hardware/power. All native access needs a versioned
 * loader handoff; device readiness and identity are checked independently. */
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <sys/errno.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_power.h>
#include <sys/mt6762_gauge.h>
#include <sys/hakios.input.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include "mt6762_power_protocol.h"
#include "mt6762_charger_protocol.h"
#include "mt6762_thermal_protocol.h"
#include "../../tools/mt6762/hardware/power/mt6762_pwrap_entry.h"
#include "../../tools/mt6762/hardware/power/mt6762_keys_entry.h"
#include "../../tools/mt6762/hardware/power/mt6762_pmic_entry.h"

static LCK_GRP_DECLARE(power_lck_group,"mt6762-power");
static LCK_MTX_DECLARE(pwrap_mutex,&power_lck_group);
static LCK_MTX_DECLARE(adc_mutex,&power_lck_group);
static volatile uint8_t *pwrap, *keypad;
static volatile uint8_t *keys_gpio,*keys_gic;
static int keys_only,keys_fault;
static int pwrap_ready, pwrap_fault, adc_ready, charger_ready, started;
static uint32_t pwrap_profile;
static int pwrap_read_only;
static volatile uint8_t *pwrap_infra;
static int pmic_id=-1, power_valid, power_errors, charger_state=-1;
static int charger_owned, charger_lab, charger_control_safe=-1, charger_control=-1;
static int adc_voltage_requests, adc_ntc_requests, adc_voltage_samples, adc_ntc_samples;
static int adc_voltage_min=-1,adc_voltage_max=-1,adc_ntc_min=-1,adc_ntc_max=-1;
static int battery_adc_mv=-1, ntc_adc_mv=-1, ntc_nominal_deci_c=-2730;
static struct mt6762_key_filter key_filter[3];
static uint32_t report_gap_start_ms,report_gap_ms;
static uint64_t report_gap_start,report_gap_end;
static int report_gap_state,reports_suppressed;

SYSCTL_DECL(_kern_hakios);
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_battery_report_gap_state,CTLFLAG_RD|CTLFLAG_LOCKED,&report_gap_state,0,"Explicit synthetic publication gap:0disabled/armed,1active,2complete");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_battery_reports_suppressed,CTLFLAG_RD|CTLFLAG_LOCKED,&reports_suppressed,0,"Reports omitted by explicit lab-only publication-gap test");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_pmic_id,CTLFLAG_RD|CTLFLAG_LOCKED,&pmic_id,0,"Observed MT6357 hardware ID, -1 unknown");
static int power_valid_sysctl SYSCTL_HANDLER_ARGS
{
    int value=(int)mt6762_battery_valid_fields();
    return sysctl_handle_int(oidp,&value,0,req);
}
SYSCTL_PROC(_kern_hakios,OID_AUTO,mt6762_power_valid,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,0,power_valid_sysctl,"I","Unexpired native battery sample validity mask");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_power_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&power_errors,0,"Native power read failures");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_charger_state,CTLFLAG_RD|CTLFLAG_LOCKED,&charger_state,0,"PSC5425E raw state 0..3, -1 unknown");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_battery_adc_mv,CTLFLAG_RD|CTLFLAG_LOCKED,&battery_adc_mv,0,"MT6357 battery ADC millivolts, -1 unknown");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_ntc_adc_mv,CTLFLAG_RD|CTLFLAG_LOCKED,&ntc_adc_mv,0,"MT6357 thermistor ADC millivolts, -1 unknown");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_ntc_nominal_deci_c,CTLFLAG_RD|CTLFLAG_LOCKED,&ntc_nominal_deci_c,0,"Uncalibrated NTC estimate, never used to enable charging; -2730 unknown");

SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_charger_control_safe,CTLFLAG_RD|CTLFLAG_LOCKED,&charger_control_safe,0,"CE readback disabled: 1; rejected 0; unknown -1. No independent fallback guarantee");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_voltage_requests,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_requests,0,"Successful battery-voltage ADC request transactions");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_ntc_requests,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_requests,0,"Successful NTC ADC request transactions");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_voltage_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_samples,0,"Valid voltage conversions");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_ntc_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_samples,0,"Valid NTC conversions, not calibrated temperature");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_voltage_min,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_min,0,"Minimum observed battery ADC mV, -1 none");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_voltage_max,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_voltage_max,0,"Maximum observed battery ADC mV, -1 none");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_ntc_min,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_min,0,"Minimum observed NTC ADC mV, -1 none");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_adc_ntc_max,CTLFLAG_RD|CTLFLAG_LOCKED,&adc_ntc_max,0,"Maximum observed NTC ADC mV, -1 none");

int mt6762_charger_control_safe(void) {return charger_control_safe==1;}

SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_charger_control,CTLFLAG_RD|CTLFLAG_LOCKED,&charger_control,0,"Last verified disabled PSC control byte; -1 unknown");

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
static void pwrap_wacs_delay(void *unused,unsigned us)
{
    uint64_t interval,start;
    (void)unused;
    if(!us)return;
    /* WACS polls request10us. GenericARMCPU has no idle-latency estimate,
     * so delay() otherwise schedules away on every not-ready poll while
     * holding pwrap_mutex. Keep these short polls synchronous, with IRQs and
     * preemption unchanged. YIELD is a CPU hint, not a scheduler operation;
     * WFE would depend on another event to wake this single-core trial. */
    if(us>10) {delay(us);return;}
    clock_interval_to_absolutetime_interval(us,NSEC_PER_USEC,&interval);
    start=mach_absolute_time();
    while(mach_absolute_time()-start<interval)
        __asm__ volatile("yield" ::: "memory");
}
static const struct mt6762_wacs_io pwrap_io={NULL,pwrap_rd,pwrap_wr,pwrap_wacs_delay};
static uint32_t pwrap_entry_read(void *unused,uint32_t address)
{
    (void)unused;
    if(address==0x10001090) {
        uint32_t value=*(volatile uint32_t *)(pwrap_infra+0x90);
        __asm__ volatile("dsb oshld":::"memory");return value;
    }
    return pwrap_rd(NULL,address-0x1000d000);
}

static int pwrap_transfer(int write,uint16_t address,uint16_t *value)
{
    int e;
    if(!value || (address&1))return -EINVAL;
    if(write && pwrap_read_only)return -EPERM;
    lck_mtx_lock(&pwrap_mutex);
    if(!pwrap_ready || pwrap_fault) {lck_mtx_unlock(&pwrap_mutex);return -ENXIO;}
    e=mt6762_wacs_transfer_profile(&pwrap_io,pwrap_profile,write,address,value);
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

static int pmic_entry_read(void *unused,uint16_t address,uint16_t *value)
{(void)unused;return mt6762_pwrap_read16(address,value);}
static void pmic_adc_entry_probe(void)
{
    /* Configuration evidence only. This API cannot request a conversion,
     * change TDET/trim, or confer ADC calibration/channel ownership. */
    if(!pwrap_ready || !pwrap_read_only || pwrap_fault)return;
    kprintf("MT6762_ADC_ENTRY_BEGIN version=1 passes=2 registers=%u conversion_requested=0 gauge_commands=0\n",
        MT6762_PMIC_ADC_ENTRY_COUNT);
    for(unsigned pass=0;pass<2;pass++) {
        struct mt6762_pmic_adc_entry_observation value;
        struct mt6762_pmic_entry_failure failure;
        int error=mt6762_pmic_adc_entry_observe(pmic_entry_read,NULL,&value,&failure);
        if(error) {
            kprintf("MT6762_ADC_ENTRY_FAILED pass=%u index=%u address=%04x error=%d transport=%d value=%04x\n",
                pass,failure.index,failure.address,error,failure.error,failure.value);
            return;
        }
        for(unsigned i=0;i<MT6762_PMIC_ADC_ENTRY_COUNT;i++)
            kprintf("MT6762_ADC_ENTRY pass=%u index=%u address=%04x value=%04x\n",
                pass,i,mt6762_pmic_adc_entry_regs[i],value.value[i]);
        kprintf("MT6762_ADC_ENTRY_COMPLETE pass=%u measurement_valid=0 ownership_grant=0 calibration_grant=0\n",pass);
    }
}
static void pmic_entry_probe(void)
{
    /* Only extend the inherited read-only observation path. No ADC/gauge
     * ownership or calibration grant is inferred from matching raw words. */
    if(!pwrap_ready || !pwrap_read_only || pwrap_fault)return;
    kprintf("MT6762_PMIC_ENTRY_BEGIN version=1 passes=2 registers=%u conversion_requested=0 gauge_commands=0\n",
        MT6762_PMIC_ENTRY_COUNT);
    for(unsigned pass=0;pass<2;pass++) {
        struct mt6762_pmic_entry_observation value;
        struct mt6762_pmic_entry_failure failure;
        int error=mt6762_pmic_entry_observe(pmic_entry_read,NULL,&value,&failure);
        if(error) {
            kprintf("MT6762_PMIC_ENTRY_FAILED pass=%u index=%u address=%04x error=%d transport=%d value=%04x\n",
                pass,failure.index,failure.address,error,failure.error,failure.value);
            return;
        }
        for(unsigned i=0;i<MT6762_PMIC_ENTRY_COUNT;i++)
            kprintf("MT6762_PMIC_ENTRY pass=%u index=%u address=%04x value=%04x\n",
                pass,i,mt6762_pmic_entry_regs[i],value.value[i]);
        kprintf("MT6762_PMIC_ENTRY_COMPLETE pass=%u measurement_valid=0 ownership_grant=0\n",pass);
    }
    /* Preserve every version1 PMIC record. A failed earlier pass returns
     * before this separate record and never starts additional reads. */
    pmic_adc_entry_probe();
}

#include "mt6762_gauge_latch_probe.c"

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
/* Shares this driver's ADC mutex and PWRAP ownership. */
#include "mt6762_bif_observer.c"
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
    static const uint32_t ids[]={HAKIOS_BUTTON_LOCK,HAKIOS_BUTTON_VOLUME_UP,
                                HAKIOS_BUTTON_VOLUME_DOWN};
    int change=mt6762_key_update(&key_filter[which],valid,pressed);
    if(change && keys_only)
        kprintf("MT6762_KEY button=%u direction=%d valid=%d\n",ids[which],change,valid);
    if(change)hakios_touch_post(change>0?HAKIOS_BUTTON_DOWN:HAKIOS_BUTTON_UP,
                               ids[which],0,0);
}
static uint32_t keys_entry_read(void *unused,uint32_t address,unsigned width)
{
    (void)unused;
    volatile uint8_t *base=address>=0x10010000?keypad:
        address>=0x10005000?keys_gpio:keys_gic;
    unsigned offset=address&0xfff;
    uint32_t value=width==2?*(volatile uint16_t *)(base+offset):
        *(volatile uint32_t *)(base+offset);
    __asm__ volatile("dsb oshld":::"memory");return value;
}
static void poll_buttons(void)
{
    if(keys_only && (keys_fault || !mt6762_keys_entry_ok(keys_entry_read,NULL))) {
        if(!keys_fault)kprintf("MT6762_KEYS fault: inherited keypad state changed\n");
        keys_fault=1;
        for(unsigned i=0;i<3;i++)button_sample(i,0,0);
        return;
    }
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
#include "mt6762_battery_observer.c"

static void poll_battery(void)
{
    struct mt6762_battery_sample s={.size=sizeof(s)};
    uint64_t duration,gauge_expires,now;
    uint16_t v;
    uint8_t id,state;
    static uint32_t last_valid=~0u;
    static int last_charger=-2,last_safe=-2;
    clock_get_uptime(&s.acquired_abs);
    clock_interval_to_absolutetime_interval(2000,NSEC_PER_MSEC,&duration);
    s.expires_abs=s.acquired_abs+duration;
    if(s.expires_abs<=s.acquired_abs)s.expires_abs=0;
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
    if(!mt6762_gauge_current_snapshot(&s.current_ua,&gauge_expires)) {
        s.valid|=MT6762_BAT_CURRENT;
        if(gauge_expires<s.expires_abs)s.expires_abs=gauge_expires;
    }
    /* Learned SOC and compensated battery NTC are not established. Their
     * validity bits remain clear; no fake percentage or25C value. */
    clock_get_uptime(&now);
    if(!s.expires_abs || now>=s.expires_abs)s.valid=0;
    power_valid=(int)s.valid;
    if(s.valid!=last_valid || charger_state!=last_charger || charger_control_safe!=last_safe) {
        printf("MT6762 power: observed valid=%#x PSC state=%d CE-safe=%d control=%d battery ADC=%d mV\n",
            s.valid,charger_state,charger_control_safe,charger_control,battery_adc_mv);
        last_valid=s.valid;last_charger=charger_state;last_safe=charger_control_safe;
    }
    /* Explicit lab test suppresses delivery only. Acquisition and button work
     * continue so BSD getters and the IOKit timer must expire independently. */
    if(report_gap_ms) {
        clock_get_uptime(&now);
        if(!report_gap_start) {
            clock_interval_to_absolutetime_interval(report_gap_start_ms,NSEC_PER_MSEC,&duration);
            report_gap_start=now+duration;
            clock_interval_to_absolutetime_interval(report_gap_ms,NSEC_PER_MSEC,&duration);
            report_gap_end=report_gap_start+duration;
        }
        if(now>=report_gap_start && now<report_gap_end) {
            if(report_gap_state!=1)printf("MT6762 power: synthetic publication gap begins; acquisition continues\n");
            report_gap_state=1;reports_suppressed++;return;
        }
        if(now>=report_gap_end && report_gap_state!=2) {
            report_gap_state=2;
            printf("MT6762 power: synthetic publication gap ends\n");
        }
    }
    mt6762_battery_report(&s);
}
static void power_thread(__unused void *parameter,__unused wait_result_t result)
{
    for(unsigned tick=0;;tick++) {
        poll_buttons();
        if(!keys_only && tick%60==0)poll_battery();
        delay_for_interval(16,NSEC_PER_MSEC);
    }
}
void mt6762_power_init(void)
{
    uint16_t id;
    thread_t thread;
    if(started || !mt6762_platform_ready())return;
    if(verified("pwrap-verified")) {
        if(mt6762_handoff_u32("pwrap-profile",&pwrap_profile))
            pwrap_profile=verified("lab-fixture")?MT6762_WACS_LEGACY21:0;
        if(pwrap_profile!=MT6762_WACS_LK22 &&
           !(pwrap_profile==MT6762_WACS_LEGACY21 && verified("lab-fixture"))) {
            kprintf("MT6762_PWRAP refused missing/unsupported profile\n");return;
        }
        pwrap_read_only=pwrap_profile==MT6762_WACS_LK22 && !verified("pwrap-write-owned");
        pwrap=mt6762_map_mmio(0x1000d000,0x1000);
        if(pwrap && pwrap_profile==MT6762_WACS_LK22) {
            pwrap_infra=mt6762_map_mmio(0x10001000,0x1000);
            if(!pwrap_infra || !mt6762_pwrap_entry_ok(pwrap_entry_read,NULL)) {
                kprintf("MT6762_PWRAP refused live inherited wrapper state\n");return;
            }
        }
        if(pwrap) {
            pwrap_ready=1;
            if(mt6762_pwrap_read16(8,&id) || (id>>8)!=0x57) {
                pwrap_ready=0;
                printf("MT6762 power: PMIC identification failed; PWRAP observations disabled\n");
            }else {
                pmic_id=id;
                kprintf("MT6762_PWRAP_READY profile=%u id=%04x read_only=%d\n",pwrap_profile,id,pwrap_read_only);
            }
        }
    }
    if(verified("pwrap-inherited-probe")) {
        /* PMIC ordinary readable words only: keys/reset policy and eMMC/CPU rails.
         * No ADC/gauge commands, rail writes or charger control. The separate
         * inherited-key grant below permits only filtered key observations. */
        static const uint16_t regs[]={0x24,0x14c,0x1988,0x1958,0x1c20,0x1996,0x1966,
            0x14a2,0x14a4,0x19cc,0x19ce};
        for(unsigned pass=0;pwrap_ready && pass<2;pass++)for(unsigned i=0;i<sizeof(regs)/sizeof(regs[0]);i++) {
            uint16_t value=0;int error=mt6762_pwrap_read16(regs[i],&value);
            kprintf("MT6762_PWRAP_SAMPLE pass=%u address=%04x error=%d value=%04x\n",pass,regs[i],error,value);
            if(error)return;
        }
        pmic_entry_probe();
        if(!verified("battery-inherited-observer"))gauge_latch_probe();
        /* Separate observation grant; bus5 still needs its own validated
         * handoff and setup. Do not enter normal ADC/charger policy below. */
        if(verified("charger-readonly-probe") && !verified("battery-inherited-observer")) {
            for(unsigned pass=0;pass<2;pass++) {
                struct mt6762_psc_observation value;
                int error=mt6762_i2c_ready(5)?mt6762_psc_observe(&psc_io,&value):-ENXIO;
                if(error) {
                    kprintf("MT6762_PSC_PROBE pass=%u error=%d\n",pass,error);
                    break;
                }
                kprintf("MT6762_PSC_PROBE pass=%u error=0 id=%02x control=%02x status=%02x\n",
                    pass,value.id,value.control,value.status);
            }
        }
        if(verified("battery-inherited-observer"))battery_inherited_start();
        if(pwrap_ready && pwrap_read_only && verified("keys-inherited-probe") && verified("keypad-verified")) {
            keypad=mt6762_map_mmio(0x10010000,0x1000);
            keys_gpio=mt6762_map_mmio(0x10005000,0x1000);
            keys_gic=mt6762_map_mmio(0x0c000000,0x1000);
            if(!keypad || !keys_gpio || !keys_gic || !mt6762_keys_entry_ok(keys_entry_read,NULL)) {
                kprintf("MT6762_KEYS refused inherited keypad state\n");return;
            }
            keys_only=1;
            if(kernel_thread_start(power_thread,NULL,&thread)==KERN_SUCCESS) {
                started=1;thread_deallocate(thread);
                kprintf("MT6762_KEYS_READY readonly=1 boot_held_suppressed=1\n");
            }
        }
        return;
    }
    adc_ready=pwrap_ready && verified("adc-verified");
    bif_init();
    if(verified("lab-fixture")) {
        uint32_t start_ms,gap_ms;
        if(!mt6762_handoff_u32("battery-report-gap-start-ms",&start_ms) &&
           !mt6762_handoff_u32("battery-report-gap-ms",&gap_ms) &&
           start_ms>=1000 && start_ms<=300000 && gap_ms>=2000 && gap_ms<=10000) {
            report_gap_start_ms=start_ms;report_gap_ms=gap_ms;
        }
    }
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
