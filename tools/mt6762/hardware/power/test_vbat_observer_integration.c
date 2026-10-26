/* Reuse the exact observer/WACS fixture; this entry exercises only VBAT. */
#define MT6762_VBAT_TEST
#include "test_battery_observer_integration.c"
#include "vbat_vectors.h"
static void vbat_start(unsigned gauge) {properties[21].value=1;start(gauge);}
int main(void)
{
    reset();vbat_start(0);battery_inherited_poll();
    assert(count==54 && adc_requests==1 && adc_voltage_requests==1 && adc_voltage_samples==1);
    assert(!battery_observer.fault && !battery_observer.vbat_fault && !adc_mutex);
    assert(published.valid==0x47 && published.voltage_uv==4119000 && pmic_writes==1);
    assert(battery_adc_mv==4119 && adc_voltage_min==4119 && adc_voltage_max==4119);
    struct txn baseline[54];memcpy(baseline,transactions,sizeof(baseline));
    assert(baseline[27].write && baseline[27].reg==0x110e && baseline[27].value==2);
    battery_inherited_poll();assert(count==54 && adc_requests==1);
    next();assert(count==108 && adc_requests==2 && published.valid==0x47);
    reset();vbat_start(1);battery_inherited_poll();assert(count==86 && pmic_writes==5 && published.valid==0x47);
    next();assert(count==172 && pmic_writes==10 && published.valid==0x4f && snapshot()==0);
    assert(published.current_ua==31400 && published.voltage_uv==4119000);
    unsigned faults=0;
    for(unsigned at=1;at<=54;at++)for(unsigned stage=0;stage<4;stage++) {
        if(stage==2 && baseline[at-1].write)continue;
        reset();vbat_start(0);fail_at=at;fail_stage=stage;battery_inherited_poll();
        assert(pwrap_fault && battery_observer.fault && !published.valid && count==at-(stage==0));
        unsigned writes=0;
        for(unsigned i=0;i<count;i++)writes+=baseline[i].write;
        assert(pmic_writes==writes && adc_requests==writes && adc_requests<=1);
        assert(!adc_mutex && !pwrap_mutex && !battery_observer.vbat_context);
        terminal();faults++;
    }
    for(unsigned at=1;at<=54;at++) {
        reset();vbat_start(0);late_at=at;battery_inherited_poll();
        assert(count==at && !pwrap_fault && battery_observer.fault && !published.valid);
        assert(adc_requests<=1 && !adc_mutex);terminal();
    }
    unsigned mutations=0;
    for(unsigned after=0;after<2;after++)for(unsigned i=0;i<24;i++) {
        reset();vbat_start(0);mutate_at=(after?30:3)+i+1;battery_inherited_poll();
        assert(count==mutate_at && !pwrap_fault && !battery_observer.fault && battery_observer.vbat_fault);
        assert(adc_requests==after && published.valid==0x43 && battery_adc_mv==-1 && !adc_voltage_samples);
        unsigned requests=adc_requests;next();assert(adc_requests==requests && published.valid==0x43);
        mutations++;
    }
    for(unsigned missing=22;missing<=27;missing++) {
        reset();properties[21].value=1;missing_property=(int)missing;
        assert(!battery_inherited_admit() && !count);
        reset();properties[21].value=1;properties[missing].value=0x10000;
        assert(!battery_inherited_admit() && !count);
    }
    for(unsigned bad=0;bad<4;bad++) {
        reset();vbat_start(0);
        switch(bad) {case 0:adc_stale=1;break;case 1:adc_timeout=1;break;case 2:adc_raw=0;break;case 3:adc_raw=0x7fff;break;}
        battery_inherited_poll();
        assert(battery_observer.vbat_fault && !battery_observer.fault && published.valid==0x43);
        assert(adc_requests==1 && adc_voltage_requests==1 && !adc_voltage_samples && battery_adc_mv==-1);
        next();assert(adc_requests==1 && published.valid==0x43);
        assert(strstr(messages,"cleanup_writes=0"));
    }
    reset();vbat_start(0);adc_delay_late=1;battery_inherited_poll();
    assert(battery_observer.fault && adc_requests==1 && !published.valid);terminal();
    reset();vbat_start(0);adc_lock_delay=2000000;battery_inherited_poll();
    assert(battery_observer.fault && count==3 && !adc_requests && !published.valid);terminal();
    for(unsigned i=0;i<sizeof(vbat_vectors)/sizeof(vbat_vectors[0]);i++) {
        reset();vbat_start(0);adc_raw=(uint16_t)vbat_vectors[i][0];battery_inherited_poll();
        if(adc_raw==0 || adc_raw==32767)assert(published.valid==0x43 && battery_observer.vbat_fault);
        else assert(published.valid==0x47 && published.voltage_uv==vbat_vectors[i][1]*1000);
    }
    /* Failure after a previously published voltage replaces its validity. */
    reset();vbat_start(1);battery_inherited_poll();next();assert(published.valid==0x4f);
    adc_stale=1;next();assert(published.valid==0x4b && battery_observer.vbat_fault && snapshot()==0);
    assert(battery_adc_mv==-1 && adc_requests==3);next();assert(adc_requests==3 && published.valid==0x4b);
    /* Callback shapes, one-shot budget, phase, identity and lease cannot be
     * expanded by a caller; general PWRAP writes stay refused throughout. */
    for(unsigned misuse=0;misuse<12;misuse++) {
        reset();vbat_start(0);
        struct vbat_observer_context ctx={.lease={now_us,now_us+2000000},.phase=2};
        battery_observer.vbat_context=&ctx;uint16_t reg=0x110e,value=2;
        switch(misuse) {
        case 0:reg=0x1110;break;case 1:reg=0x1236;break;case 2:value=8;break;
        case 3:ctx.attempted=1;break;case 4:ctx.phase=1;break;case 5:ctx.phase=3;break;
        case 6:battery_observer.vbat_context=NULL;break;case 7:battery_observer.vbat_fault=1;break;
        case 8:battery_observer.active=0;break;case 9:now_us=ctx.lease.end;break;
        case 10:now_us=ctx.lease.start-1;break;case 11:ctx.fault=1;break;
        }
        assert(vbat_observer_write(&ctx,reg,value)<0 && !count && ctx.fault);
        assert(vbat_observer_write(&ctx,0x110e,2)<0 && !count);
        assert(mt6762_pwrap_write16(0x110e,2)==-EPERM && !count);
    }
    reset();vbat_start(0);struct vbat_observer_context ctx={.lease={now_us,now_us+2000000},.phase=2};
    battery_observer.vbat_context=&ctx;uint16_t raw=42;
    assert(vbat_observer_read(&ctx,0x108a,&raw)<0 && raw==42 && !count); /* no request */
    reset();vbat_start(0);ctx=(struct vbat_observer_context){.lease={now_us,now_us+2000000},.phase=2};
    battery_observer.vbat_context=&ctx;
    assert(!vbat_observer_write(&ctx,0x110e,2) && adc_requests==1);
    assert(vbat_observer_write(&ctx,0x110e,2)<0 && adc_requests==1);
    printf("actual native VBAT observer: %u WACS faults, %u shadow changes, 54 expiry positions, generation/lease/publication/private one-shot gates PASS\n",faults,mutations);
}
