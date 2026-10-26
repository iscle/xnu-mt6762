/* Executes the actual private probe, public PWRAP guard and unmodified gauge
 * and WACS protocols. Only clock/lock/MMIO/handoff/log primitives are fakes. */
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define NSEC_PER_MSEC 1000000u
#define LCK_MTX_DECLARE(name,group) int name
#include "../../../../bsd/dev/mt6762_power_protocol.h"
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
static char messages[65536];
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
    {"charger-verified",0},{"charger-control-owned",0},{"pwrap-write-owned",0},{"lab-fixture",0}
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
static int mt6762_pwrap_write16(uint16_t,uint16_t);
static uint16_t pmic_read(uint16_t reg) {
    switch(reg) {
    case 8:return 0x5730;case 0xc0c:return 4;case 0xd08:return 0x129;
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
    assert(reg==0xd0a && pmic_writes<8 && value==order[pmic_writes%4]);
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
#include "gauge_latch_power_functions.c"
#include "../../../../bsd/dev/mt6762_gauge_latch_probe.c"
static void reset(void) {
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
    for(unsigned i=0;i<sizeof(properties)/sizeof(properties[0]);i++)properties[i].value=defaults[i];
}
static const char *ending(void) {
    const char *p=strstr(messages,"MT6762_GAUGE_LATCH_END ");
    assert(p && !strstr(p+1,"MT6762_GAUGE_LATCH_END "));
    assert(strstr(p,"cleanup_writes=0") && strstr(p,"measurement_published=0 ownership_grant=0"));
    assert(!pwrap_mutex && !gauge_latch_mutex);
    return p;
}
static void terminal(void) {
    unsigned saved=count,saved_writes=pmic_writes;
    gauge_latch_probe();assert(count==saved && pmic_writes==saved_writes);
    assert(mt6762_pwrap_write16(0xd0a,1)==-EPERM && count==saved);
}
int main(void) {
    char timeout[40];snprintf(timeout,sizeof(timeout),"last_error=%d",-ETIMEDOUT);
    reset();gauge_latch_probe();
    assert(strstr(ending(),"stage=complete error=0 samples=2 writes_attempted=8 writes_completed=8"));
    assert(strstr(ending(),"latch_idle_observed=1 cleanup_writes=0 diagnostic_valid=1"));
    assert(count==64 && pmic_writes==8 && blocked_public_writes==count && control==0);
    assert(strstr(messages,"coefficient_current_ua=31400") && strstr(messages,"nter_progress=0 diagnostic_valid=0"));
    struct txn baseline[64];memcpy(baseline,transactions,sizeof(baseline));terminal();
    /* All real WACS transactions: loss before command, ambiguous completion,
     * bounded response timeout; read VLDCLR completion failure is separate. */
    unsigned transport_cases=0;
    for(unsigned at=1;at<=64;at++)for(unsigned stage=0;stage<4;stage++) {
        if(stage==2 && baseline[at-1].write)continue;
        reset();fail_at=at;fail_stage=stage;gauge_latch_probe();
        assert(pwrap_fault && count==at-(stage==0) && pmic_writes<=8);
        assert(strstr(ending(),"diagnostic_valid=0") && !strstr(ending(),"stage=complete"));
        assert(strstr(ending(),"latch_idle_observed=0"));
        if(stage==3)assert(polls>=1000);
        unsigned expected_writes=0;
        for(unsigned i=0;i<count;i++)expected_writes+=baseline[i].write;
        assert(pmic_writes==expected_writes); /* No cleanup command follows. */
        terminal();transport_cases++;
    }
    /* Every exact configuration word, both before and after both snapshots. */
    unsigned configuration_cases=0;
    for(unsigned sample=0;sample<2;sample++)for(unsigned after=0;after<2;after++)for(unsigned i=0;i<8;i++) {
        unsigned at=sample*32+(after?24:0)+i+1;
        reset();mutate_at=at;gauge_latch_probe();
        assert(count==at && !pwrap_fault && strstr(messages,"MT6762_GAUGE_LATCH_CONFIG_FAILED"));
        assert(strstr(ending(),"diagnostic_valid=0"));terminal();configuration_cases++;
    }
    for(unsigned missing=0;missing<10;missing++) {
        reset();missing_property=(int)missing;gauge_latch_probe();assert(!count && !pmic_writes);
        if(missing) {assert(strstr(ending(),"stage=handoff"));terminal();}
        else assert(!messages[0]);
    }
    for(unsigned wrong=0;wrong<17;wrong++) {
        reset();properties[wrong].value^=wrong<10?2:1;gauge_latch_probe();assert(!count);
        if(wrong) {assert(strstr(ending(),"stage=handoff"));terminal();}
        else assert(!messages[0]);
    }
    for(unsigned gate=0;gate<7;gate++) {
        reset();
        switch(gate) {
        case 0:pwrap_ready=0;break;case 1:pwrap_fault=1;break;case 2:pwrap_read_only=0;break;
        case 3:pwrap_profile=MT6762_WACS_LEGACY21;break;case 4:adc_ready=1;break;
        case 5:charger_ready=1;break;case 6:charger_owned=1;break;
        }
        gauge_latch_probe();assert(!count && strstr(ending(),"stage=wrapper"));
        if(pwrap_read_only)terminal();
    }
    /* Known success has full release. Every failed handshake stops at its
     * last issued command; no uncertain latch is silently called clean. */
    reset();no_ready=1;gauge_latch_probe();assert(pmic_writes==1 && control==1);assert(strstr(ending(),"latch_idle_observed=0"));terminal();
    reset();no_release=1;gauge_latch_probe();assert(pmic_writes==3 && control==0x8008);assert(strstr(ending(),"latch_idle_observed=0"));terminal();
    reset();bad_control=1;gauge_latch_probe();assert(pmic_writes==1 && control==0x8003);terminal();
    reset();bad_top=1;gauge_latch_probe();assert(pmic_writes==1 && control==0x8001);terminal();
    reset();bad_final=1;gauge_latch_probe();assert(pmic_writes==4 && control==2);assert(strstr(ending(),"latch_idle_observed=0"));terminal();
    for(unsigned kind=0;kind<3;kind++) {
        reset();tick_delta=kind==0?0:kind==1?(1ull<<33)-1:1ull<<32;gauge_latch_probe();
        assert(count==64 && !control && strstr(ending(),"stage=nter") && strstr(ending(),"diagnostic_valid=0"));terminal();
    }
    reset();ticks=(1ull<<33)-1;gauge_latch_probe();assert(strstr(ending(),"stage=complete error=0"));
    reset();current_word=0xff9b;car_high=0xff9b;car_low=0xf800;gauge_latch_probe();
    assert(strstr(messages,"coefficient_current_ua=-31400") && strstr(messages,"coefficient_charge_uah=-"));
    /* Expiry during every transaction, including final data/config reads and
     * every write completion. It never admits the next operation. */
    for(unsigned at=1;at<=64;at++) {
        reset();late_at=at;gauge_latch_probe();assert(count==at && !pwrap_fault);
        assert(strstr(ending(),"diagnostic_valid=0") && strstr(ending(),timeout));terminal();
    }
    reset();lock_delay_at=2;lock_delay=2000000;gauge_latch_probe();assert(!count && strstr(ending(),timeout));
    reset();interval_preemption=2000000;gauge_latch_probe();assert(!count && strstr(ending(),timeout));
    reset();now_us=UINT64_MAX-1000;gauge_latch_probe();assert(!count && strstr(ending(),"stage=lease"));
    reset();separation_us=999999;gauge_latch_probe();assert(count==32 && pmic_writes==4 && strstr(ending(),"stage=lease"));
    /* A rogue private callback cannot bypass arming, address/value/phase,
     * write budget, expired lease or terminal fault. */
    for(unsigned misuse=0;misuse<7;misuse++) {
        reset();struct gauge_latch_context c={.acquired=now_us,.deadline=now_us+2000000};
        assert(mt6762_gauge_probe_begin(&c.budget,0));
        if(misuse!=0)assert(mt6762_gauge_probe_arm(&c.budget));
        uint16_t reg=0xd0a,val=1;
        if(misuse==1)reg=0x110e;
        if(misuse==2)val=9;
        if(misuse==3)c.budget.attempted=c.budget.completed=8;
        if(misuse==4)c.budget.fault=1;
        if(misuse==5)now_us=c.deadline;
        if(misuse==6)now_us=c.acquired-1;
        assert(gauge_latch_write(&c,reg,val)<0 && !count && c.budget.fault);
        assert(gauge_latch_write(&c,0xd0a,1)<0 && !count);
    }
    reset();struct gauge_latch_context c={.acquired=now_us,.deadline=now_us+2000000};uint16_t word=42;
    assert(mt6762_gauge_probe_begin(&c.budget,0));
    assert(gauge_latch_read(&c,0xd8a,&word)<0 && word==42 && !count);
    printf("actual gauge latch/WACS integration: %u transport faults, %u config changes, 64 expiry positions, phase/lease/cleanup/public-write gates PASS\n",
        transport_cases,configuration_cases);
}
