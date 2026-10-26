/* Actual inherited battery observer + unchanged gauge/PSC/WACS protocols.
 * Clock, locks, MMIO, handoff and publication are modeled; no hardware I/O. */
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define NSEC_PER_MSEC 1000000u
#define LCK_MTX_DECLARE(name,group) int name
#include "../../../../bsd/dev/mt6762_power_protocol.h"
#include "../../../../bsd/dev/mt6762_charger_protocol.h"
#include "../../../../bsd/sys/mt6762_power.h"
static int pwrap_mutex;
static int pwrap_ready,pwrap_fault,pwrap_read_only,adc_ready,charger_ready,charger_owned;
static uint32_t pwrap_profile;
static uint64_t now_us,lock_delay,interval_preemption,transaction_delay,separation_us;
static unsigned lock_calls,lock_delay_at,late_at;
static void lck_mtx_lock(int *m) {
    assert(!*m);*m=1;
    if(m==&pwrap_mutex && ++lock_calls==lock_delay_at)now_us+=lock_delay;
}
static void lck_mtx_unlock(int *m){assert(*m);*m=0;}
static void clock_get_uptime(uint64_t *v){*v=now_us;}
static void clock_interval_to_absolutetime_interval(unsigned n,unsigned scale,uint64_t *v)
{assert(scale==NSEC_PER_MSEC);*v=(uint64_t)n*1000;now_us+=interval_preemption;}
static void delay_for_interval(unsigned n,unsigned scale)
{assert(n==1000 && scale==NSEC_PER_MSEC);now_us+=separation_us;}
static void pwrap_wacs_delay(void *unused,unsigned us){(void)unused;assert(us==10);now_us+=us;}
static char messages[131072];
static void kprintf(const char *format,...) {
    va_list ap;va_start(ap,format);
    size_t used=strlen(messages);
    int n=vsnprintf(messages+used,sizeof(messages)-used,format,ap);
    va_end(ap);assert(n>=0 && (size_t)n<sizeof(messages)-used);
}
struct prop {const char *name;uint32_t value;};
static struct prop properties[]={
    {"fgauge-latch-probe",1},{"pwrap-inherited-probe",1},
    {"fgauge-baseline-version",1},{"fgauge-rfg",100},{"fgauge-car-tune",1000},
    {"fgauge-con0",0x129},{"fgauge-efuse-gain",0x416},{"fgauge-efuse-offset",1},
    {"fgauge-adjust-offset",0},{"fgauge-gain",0x416},
    {"fgauge-owned",0},{"fgauge-calibration-verified",0},{"adc-verified",0},
    {"charger-verified",0},{"charger-control-owned",0},{"pwrap-write-owned",0},{"lab-fixture",0},
    {"battery-inherited-observer",1},{"fgauge-inherited-observer",0},
    {"charger-readonly-probe",0},{"charger-setup-only",0}
};
static int missing_property;
static int mt6762_handoff_u32(const char *name,uint32_t *value) {
    for(unsigned i=0;i<sizeof(properties)/sizeof(properties[0]);i++)
        if((int)i!=missing_property && !strcmp(name,properties[i].name)) {*value=properties[i].value;return 0;}
    return -1;
}
struct txn {uint16_t reg,value;unsigned write;uint64_t when;};
static struct txn transactions[4096];
static unsigned count,pmic_writes,requests,phase,command_write,fail_at,fail_stage,mutate_at;
static unsigned blocked_public_writes,polls,no_ready,no_release,bad_control,bad_top,bad_final;
static uint16_t control,response,mutate_mask,current_word,car_low,car_high;
static uint64_t ticks,tick_delta;
static uint16_t external_word,present_word;
static int mt6762_pwrap_write16(uint16_t,uint16_t);
static uint16_t pmic_read(uint16_t reg) {
    switch(reg) {
    case 8:return 0x5730;case 0xc0c:return 4;case 0xd08:return 0x129;
    case 0x24:return external_word;case 0xe08:return present_word;
    case 0xc8e:case 0xd96:return 0x416;case 0xc90:return 1;case 0xd94:return 0;
    case 0xd0a:return control;case 0xd8a:return current_word;
    case 0xd12:return car_low;case 0xd14:return car_high;
    case 0xd20:return (uint16_t)ticks;case 0xd22:return (uint16_t)(ticks>>16);
    case 0xd24:return bad_top?2:(uint16_t)(ticks>>32);
    default:assert(0);return 0;
    }
}
static void pmic_write(uint16_t reg,uint16_t value) {
    static const uint16_t order[]={1,9,8,0};
    assert(reg==0xd0a && pmic_writes<128 && value==order[pmic_writes%4]);
    pmic_writes++;
    if(value==1) {
        if(requests++)ticks=(ticks+tick_delta)&((1ull<<33)-1);
        control=no_ready?1:(bad_control?0x8003:0x8001);
    }else if(value==9)control=0x8009;
    else if(value==8)control=no_release?0x8008:8;
    else control=bad_final?2:0;
}
static uint32_t mmio_read(void *unused,uint32_t offset) {
    (void)unused;assert(offset==0xc24 && pwrap_mutex);polls++;
    if(!phase) {
        if(count+1==fail_at && fail_stage==0)return 0; /* No command issued. */
        return 1u<<22;
    }
    if(count==fail_at) {
        if((fail_stage==1 && phase==1) || (fail_stage==2 && phase==2))return 0;
        if(fail_stage==3 && phase==1)return (1u<<22)|(7u<<16);
    }
    if(command_write || phase==2){phase=0;return 1u<<22;}
    return (1u<<22)|(6u<<16)|response;
}
static void mmio_write(void *unused,uint32_t offset,uint32_t word) {
    (void)unused;assert(pwrap_mutex);
    if(offset==0xc28) {assert(phase==1 && !command_write && word==1);phase=2;return;}
    assert(offset==0xc20 && !phase && count<4096);
    command_write=word>>31;
    uint16_t reg=(uint16_t)(((word>>16)&0x7fff)<<1),value=(uint16_t)word;
    transactions[count++]=(struct txn){reg,value,command_write,now_us};
    assert(mt6762_pwrap_write16(0xd0a,0)==-EPERM);blocked_public_writes++;
    if(command_write)pmic_write(reg,value);
    else {response=pmic_read(reg);if(count==mutate_at)response^=mutate_mask;}
    phase=1;now_us+=transaction_delay;
    if(count==late_at)now_us+=2000000;
}
static const struct mt6762_wacs_io pwrap_io={NULL,mmio_read,mmio_write,pwrap_wacs_delay};
/* Generated verbatim from mt6762_power.c by the test runner. */
#include "battery_observer_power_functions.c"
#include "../../../../bsd/dev/mt6762_gauge_latch_probe.c"
static void reset_transport(void) {
    gauge_latch_started=0;pwrap_mutex=gauge_latch_mutex=0;
    pwrap_ready=pwrap_read_only=1;pwrap_fault=adc_ready=charger_ready=charger_owned=0;
    pwrap_profile=MT6762_WACS_LK22;now_us=1000;
    lock_delay=interval_preemption=transaction_delay=0;separation_us=1000000;
    lock_calls=lock_delay_at=late_at=0;
    count=pmic_writes=requests=phase=command_write=fail_at=fail_stage=mutate_at=0;
    blocked_public_writes=polls=no_ready=no_release=bad_control=bad_top=bad_final=0;
    control=response=0;mutate_mask=1;current_word=100;car_low=0;car_high=1;ticks=10;tick_delta=1;
    messages[0]=0;missing_property=-1;
    const uint32_t defaults[]={1,1,1,100,1000,0x129,0x416,1,0,0x416,0,0,0,0,0,0,0};
    for(unsigned i=0;i<sizeof(defaults)/sizeof(defaults[0]);i++)properties[i].value=defaults[i];
}

static int i2c_ready,charger_state,power_valid,power_errors;
static unsigned psc_reads,psc_fail_at,psc_late_at,reports;
static uint8_t psc_id,psc_control,psc_status;
static int mt6762_i2c_ready(unsigned bus){assert(bus==5);return i2c_ready;}
static int charger_read(uint8_t reg,uint8_t *value)
{
    static const uint8_t order[]={3,1,0};
    assert(i2c_ready && reg==order[psc_reads%3]);
    psc_reads++;
    if(psc_reads==psc_fail_at)return -EIO;
    *value=reg==3?psc_id:reg==1?psc_control:psc_status;
    if(psc_reads==psc_late_at)now_us+=2000000;
    return 0;
}
static struct mt6762_battery_sample published;
static void mt6762_battery_report(const struct mt6762_battery_sample *sample);
#define MT6762_BATTERY_OBSERVER_HOST_TEST
#include "../../../../bsd/dev/mt6762_battery_observer.c"
#include "battery_observer_gauge_getters.c"
static void mt6762_battery_report(const struct mt6762_battery_sample *sample)
{
    assert(!battery_observer_mutex && !pwrap_mutex);
    assert(sample->size==sizeof(*sample));
    assert(!(sample->valid & (MT6762_BAT_SOC|MT6762_BAT_TEMP|MT6762_BAT_VOLTAGE)));
    published=*sample;reports++;
}
static void reset(void)
{
    reset_transport();
    memset(&battery_observer,0,sizeof(battery_observer));battery_observer_mutex=0;
    gauge_mutex=valid=0;memset(&observation,0,sizeof(observation));
    memset(&published,0,sizeof(published));reports=0;
    psc_reads=psc_fail_at=psc_late_at=0;psc_id=0xf0;psc_control=0xf8;psc_status=0x10;
    external_word=0xe;present_word=5;i2c_ready=1;power_valid=power_errors=0;charger_state=-1;
    properties[0].value=0;properties[17].value=1;
    properties[18].value=properties[19].value=properties[20].value=0;
}
static void start(unsigned gauge)
{
    properties[18].value=gauge;
    assert(battery_inherited_admit());assert(!battery_inherited_admit());
    assert(!count && !psc_reads && !pmic_writes);
}
static void next(void){now_us=battery_observer.next;battery_inherited_poll();}
static void terminal(void)
{
    unsigned n=count,w=pmic_writes,p=psc_reads,r=reports;
    now_us+=3000000;battery_inherited_poll();
    assert(count==n && pmic_writes==w && psc_reads==p && reports==r);
    assert(!battery_inherited_admit());
    assert(mt6762_pwrap_write16(0xd0a,1)==-EPERM && count==n);
}
static int snapshot(void)
{
    int current=42;int64_t charge=43;uint64_t acquired=44,expires=45;
    int error=mt6762_inherited_gauge_snapshot(&current,&charge,&acquired,&expires);
    if(error)assert(current==42 && charge==43 && acquired==44 && expires==45);
    else {
        assert(current==battery_observer.current && charge==battery_observer.charge);
        assert(acquired==battery_observer.acquired && expires==battery_observer.expires);
    }
    return error;
}
int main(void)
{
    int api_current=123;
    uint64_t api_expires=456;
    reset();assert(snapshot()==-ENXIO);battery_inherited_poll();assert(!count && !reports);
    start(0);battery_inherited_poll();
    assert(!battery_observer.fault && count==3 && !pmic_writes && psc_reads==3 && reports==1);
    assert(published.valid==0x43 && published.external==1 && published.present==1 && published.status==1);
    assert(snapshot()==-ENXIO && power_valid==0x43);
    uint64_t expiry=published.expires_abs;
    battery_inherited_poll();assert(count==3 && reports==1);
    now_us=battery_observer.next-1;battery_inherited_poll();assert(count==3 && reports==1);
    next();assert(count==6 && reports==2 && published.expires_abs>expiry && !pmic_writes);
    reset();start(1);battery_inherited_poll();
    assert(!battery_observer.fault && !battery_observer.gauge_fault);
    assert(count==35 && pmic_writes==4 && !control && published.valid==0x43 && snapshot()==-EAGAIN);
    valid=1;observation=(struct gauge_observation){999,999,now_us,now_us+2000000};
    assert(mt6762_gauge_current_snapshot(&api_current,&api_expires)==-EAGAIN);
    assert(api_current==123 && api_expires==456); /* No fallback to an unrelated old cache. */
    next();assert(count==70 && pmic_writes==8 && !control && published.valid==0x4b && snapshot()==0);
    assert(published.current_ua==31400 && battery_observer.charge>0);
    assert(!mt6762_gauge_current_snapshot(&api_current,&api_expires));
    assert(api_current==31400 && api_expires==published.expires_abs);
    assert(strstr(messages,"soc_valid=0 absolute_calibration=0"));
    struct txn baseline[70];memcpy(baseline,transactions,sizeof(baseline));
    next();assert(count==105 && pmic_writes==12 && published.valid==0x4b);
    now_us=battery_observer.expires;assert(snapshot()==-EAGAIN);
    assert(mt6762_gauge_current_read(&api_current)==-EAGAIN);
    unsigned transport_cases=0;
    for(unsigned at=1;at<=70;at++)for(unsigned stage=0;stage<4;stage++) {
        if(stage==2 && baseline[at-1].write)continue;
        reset();start(1);fail_at=at;fail_stage=stage;battery_inherited_poll();
        if(at>35)next();
        assert(pwrap_fault && battery_observer.fault && count==at-(stage==0));
        assert(!published.valid && snapshot()==-EAGAIN);
        unsigned expected_writes=0;
        for(unsigned i=0;i<count;i++)expected_writes+=baseline[i].write;
        assert(pmic_writes==expected_writes && pmic_writes<=8);
        terminal();transport_cases++;
    }
    unsigned config_cases=0;
    for(unsigned after=0;after<2;after++)for(unsigned i=0;i<8;i++) {
        reset();start(1);mutate_at=3+(after?24:0)+i+1;battery_inherited_poll();
        assert(!pwrap_fault && !battery_observer.fault && battery_observer.gauge_fault);
        assert(count==mutate_at && published.valid==0x43 && snapshot()==-EAGAIN);
        unsigned writes=pmic_writes;
        next();assert(pmic_writes==writes && published.valid==0x43 && psc_reads==6);
        config_cases++;
    }
    for(unsigned at=1;at<=70;at++) {
        reset();start(1);late_at=at;battery_inherited_poll();if(at>35)next();
        assert(count==at && !pwrap_fault && battery_observer.fault && !published.valid);
        assert(snapshot()==-EAGAIN);terminal();
    }
    for(unsigned at=1;at<=6;at++) {
        reset();start(1);psc_fail_at=at;battery_inherited_poll();if(at>3)next();
        assert(battery_observer.fault && !published.valid && psc_reads==at);
        assert(pmic_writes==(at>3?4:0));terminal();
        reset();start(1);psc_late_at=at;battery_inherited_poll();if(at>3)next();
        assert(battery_observer.fault && !published.valid && psc_reads==at);terminal();
    }
    /* Exact optional profile and every explicitly conflicting grant. */
    for(unsigned i=1;i<10;i++) {
        reset();properties[18].value=1;missing_property=(int)i;
        assert(!battery_inherited_admit() && !count && !psc_reads);
        reset();properties[18].value=1;properties[i].value^=2;
        assert(!battery_inherited_admit() && !count && !psc_reads);
    }
    for(unsigned i=0;i<21;i++)if(i==0 || (i>=10 && i<=16) || i>=19) {
        reset();properties[i].value=1;assert(!battery_inherited_admit() && !count);
    }
    for(unsigned gate=0;gate<8;gate++) {
        reset();
        switch(gate) {
        case 0:pwrap_ready=0;break;case 1:pwrap_fault=1;break;case 2:pwrap_read_only=0;break;
        case 3:pwrap_profile=MT6762_WACS_LEGACY21;break;case 4:adc_ready=1;break;
        case 5:charger_ready=1;break;case 6:charger_owned=1;break;case 7:i2c_ready=0;break;
        }
        assert(!battery_inherited_admit() && !count && !psc_reads);
    }
    /* Malformed PMIC/PSC observations cannot become charging state. */
    reset();start(0);mutate_at=1;battery_inherited_poll();assert(battery_observer.fault && !psc_reads);terminal();
    reset();start(0);psc_id=0xf1;battery_inherited_poll();assert(battery_observer.fault && !published.valid);terminal();
    for(unsigned bad=0;bad<8;bad++) {
        reset();start(0);
        switch(bad) {
        case 0:psc_control|=1;break;case 1:psc_control|=2;break;case 2:psc_control|=4;break;
        case 3:psc_status|=8;break;case 4:psc_status|=1;break;case 5:psc_status=0x30;break;
        case 6:external_word&=~4u;break;case 7:present_word|=2;break;
        }
        battery_inherited_poll();assert(published.valid==3 && !battery_observer.fault && !pmic_writes);
    }
    reset();start(0);present_word=0;battery_inherited_poll();assert(published.valid==2);
    reset();start(0);psc_status=0;battery_inherited_poll();assert(published.valid==0x43 && published.status==3);
    reset();start(0);psc_status=0x20;battery_inherited_poll();assert(published.valid==0x43 && published.status==4);
    /* Freshness requires a completed advancing 33-bit NTER, not simply CAR. */
    for(unsigned kind=0;kind<3;kind++) {
        reset();start(1);tick_delta=kind==0?0:kind==1?(1ull<<33)-1:1ull<<32;
        battery_inherited_poll();next();assert(battery_observer.gauge_fault && !battery_observer.fault);
        assert(published.valid==0x43 && snapshot()==-EAGAIN && pmic_writes==8 && !control);
        next();assert(pmic_writes==8 && published.valid==0x43);
    }
    reset();start(1);ticks=(1ull<<33)-1;battery_inherited_poll();next();assert(snapshot()==0);
    reset();start(1);current_word=0xff9b;car_high=0xff9b;car_low=0xf800;
    battery_inherited_poll();next();assert(published.current_ua==-31400 && battery_observer.charge<0 && snapshot()==0);
    /* Protocol failure is terminal for gauge alone; no unsafe latch cleanup. */
    for(unsigned kind=0;kind<5;kind++) {
        reset();start(1);
        switch(kind) {case 0:no_ready=1;break;case 1:no_release=1;break;case 2:bad_control=1;break;case 3:bad_top=1;break;case 4:bad_final=1;break;}
        battery_inherited_poll();assert(battery_observer.gauge_fault && !battery_observer.fault);
        unsigned writes=pmic_writes;assert(control && writes && writes<=4 && published.valid==0x43);
        next();assert(pmic_writes==writes && published.valid==0x43);
        assert(strstr(messages,"cleanup_writes=0"));
    }
    reset();start(1);interval_preemption=2000000;battery_inherited_poll();
    assert(!count && battery_observer.fault && !published.valid);terminal();
    reset();start(1);now_us=UINT64_MAX-1000;battery_inherited_poll();
    assert(!count && battery_observer.fault && !published.valid);
    reset();start(1);battery_inherited_poll();now_us=battery_observer.last_start-1;battery_inherited_poll();
    assert(battery_observer.fault && !published.valid);terminal();
    /* A callback needs the currently admitted context and may never issue a
     * fifth write, jump phases, arm sample1, or replace/renew the lease. */
    for(unsigned misuse=0;misuse<10;misuse++) {
        reset();start(1);struct gauge_latch_context ctx={.acquired=now_us,.deadline=now_us+2000000};
        assert(mt6762_gauge_probe_begin(&ctx.budget,0));
        if(misuse!=0)assert(mt6762_gauge_probe_arm(&ctx.budget));
        battery_observer.gauge_context=&ctx;
        uint16_t reg=0xd0a,value=1;
        switch(misuse) {
        case 1:reg=0x110e;break;case 2:value=9;break;case 3:ctx.budget.attempted=4;break;
        case 4:ctx.budget.next_sample=1;break;case 5:battery_observer.gauge_context=NULL;break;
        case 6:battery_observer.gauge_fault=1;break;case 7:battery_observer.fault=1;break;
        case 8:now_us=ctx.deadline;break;case 9:battery_observer.active=0;break;
        }
        assert(battery_observer_gauge_write(&ctx,reg,value)<0 && !count && ctx.budget.fault);
        assert(battery_observer_gauge_write(&ctx,0xd0a,1)<0 && !count);
    }
    printf("actual inherited battery observer: %u WACS faults, %u config changes, 70 expiry positions, PSC/status/lease/period/budget/cleanup/cache gates PASS\n",transport_cases,config_cases);
}
