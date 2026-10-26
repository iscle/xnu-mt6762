/* Calibrated temperature observation; no frequency/rail/thermal control.
 * CPU snapshots explicitly lack conversion freshness proof. PMIC conversion
 * completion requires READY low->high under exclusive ADC ownership. */
#ifndef MT6762_THERMAL_HOST_TEST
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <sys/errno.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_power.h>
#include <sys/mt6762_thermal.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#endif
#include "mt6762_thermal_protocol.h"

static LCK_GRP_DECLARE(thermal_group,"mt6762-thermal");
static LCK_MTX_DECLARE(thermal_lock,&thermal_group);
static uintptr_t controller,efuse;
static int errors,samples;
static int temperatures[8],observed_mask;
static uint64_t acquisitions[8],deadlines[8];
static unsigned valid_mask(uint64_t now)
{
    unsigned mask=mt6762_thermal_unexpired((unsigned)observed_mask,deadlines,now);
    for(unsigned i=0;i<8;i++)if(now<acquisitions[i])mask&=~(1u<<i);
    return mask;
}
#ifndef MT6762_THERMAL_HOST_TEST
static int started,pmic_enabled,cpu_enabled;
SYSCTL_DECL(_kern_hakios);
/* Every read checks expiry; a stopped worker cannot keep stale validity. */
static int thermal_sysctl SYSCTL_HANDLER_ARGS
{
    uint64_t now;
    int value=-273000;
    (void)oidp;(void)arg1;
    lck_mtx_lock(&thermal_lock);
    clock_get_uptime(&now);
    if(arg2<8) {
        if(valid_mask(now)&(1u<<arg2))value=temperatures[arg2];
    }else {
        value=(int)valid_mask(now);
        if(arg2==9)value&=7; /* Only PMIC0..2 have measured conversion freshness. */
    }
    lck_mtx_unlock(&thermal_lock);
    return sysctl_handle_int(oidp,&value,0,req);
}
#define THERM_SYSCTL(name,index,description) SYSCTL_PROC(_kern_hakios,OID_AUTO,name,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED,NULL,index,thermal_sysctl,"I",description)
THERM_SYSCTL(mt6762_pmic_die_mc,0,"Calibrated PMIC die mC; -273000 invalid/stale");
THERM_SYSCTL(mt6762_pmic_buck1_mc,1,"Calibrated PMIC VCORE sensor mC; -273000 invalid/stale");
THERM_SYSCTL(mt6762_pmic_buck2_mc,2,"Calibrated PMIC VPROC sensor mC; -273000 invalid/stale");
THERM_SYSCTL(mt6762_cpu_ts1_mc,3,"Calibrated CPU TS1 cached observation; freshness unknown");
THERM_SYSCTL(mt6762_cpu_ts2_mc,4,"Calibrated CPU TS2 cached observation; freshness unknown");
THERM_SYSCTL(mt6762_cpu_ts3_mc,5,"Calibrated CPU TS3 cached observation; freshness unknown");
THERM_SYSCTL(mt6762_cpu_ts4_mc,6,"Calibrated CPU TS4 cached observation; freshness unknown");
THERM_SYSCTL(mt6762_cpu_ts5_mc,7,"Calibrated CPU TS5 cached observation; freshness unknown");
THERM_SYSCTL(mt6762_thermal_observed,8,"Unexpired observation bits: PMIC0..2 CPU3..7; not control readiness");
THERM_SYSCTL(mt6762_thermal_fresh,9,"Fresh calibrated conversions; CPU bits remain clear");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_thermal_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&errors,0,"Rejected calibration/sensor observations");
SYSCTL_INT(_kern_hakios,OID_AUTO,mt6762_thermal_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&samples,0,"Successful sensor observations");
#endif
int mt6762_pmic_temperature_read(unsigned sensor,int *mc)
{
    int e=-ENXIO;
    uint64_t now;
    if(sensor>=3 || !mc)return -EINVAL;
    lck_mtx_lock(&thermal_lock);
    clock_get_uptime(&now);
    if(valid_mask(now)&(1u<<sensor)) {*mc=temperatures[sensor];e=0;}
    lck_mtx_unlock(&thermal_lock);
    return e;
}
#ifndef MT6762_THERMAL_HOST_TEST
static int flag(const char *name)
{uint32_t v;return !mt6762_handoff_u32(name,&v) && v==1;}
static uint32_t reg32(uintptr_t base,unsigned off)
{
    uint32_t v=*(volatile uint32_t *)(base+off);
    __asm__ volatile("dmb oshld":::"memory");return v;
}
#endif
static int sample_window(uint64_t *acquired,uint64_t *expires)
{
    uint64_t duration;
    clock_get_uptime(acquired);
    clock_interval_to_absolutetime_interval(2000,NSEC_PER_MSEC,&duration);
    *expires=0;
    if(!duration || UINT64_MAX-*acquired<duration)return 0;
    *expires=*acquired+duration;
    return 1;
}
static void publish(unsigned sensor,int valid,int mc,uint64_t acquired,uint64_t expires)
{
    uint64_t now;
    lck_mtx_lock(&thermal_lock);
    clock_get_uptime(&now);
    observed_mask&=~(1u<<sensor);deadlines[sensor]=0;
    if(valid && now>=acquired && now<expires) {
        temperatures[sensor]=mc;
        acquisitions[sensor]=acquired;deadlines[sensor]=expires;
        observed_mask|=1u<<sensor;samples++;
    }else errors++;
    lck_mtx_unlock(&thermal_lock);
}
static void sample_pmic(void)
{
    struct mt6762_pmic_cal cal;
    uint16_t a[6],b[6],id,raw;
    uint64_t acquired,expires;
    /* Calibration, conversion and publication delays all consume this lease. */
    int valid=sample_window(&acquired,&expires),mc=0;
    if(valid && (mt6762_pwrap_read16(8,&id) || (id>>8)!=0x57))valid=0;
    for(unsigned i=0;valid && i<6;i++)if(mt6762_pwrap_read16((uint16_t)(0x11ae + 2*i),&a[i]))valid=0;
    for(unsigned i=0;valid && i<6;i++)if(mt6762_pwrap_read16((uint16_t)(0x11ae + 2*i),&b[i]) || a[i]!=b[i])valid=0;
    if(valid && mt6762_pmic_cal_decode(a,&cal))valid=0;
    for(unsigned i=0;i<3;i++) {
        int ok=valid && !mt6762_pmic_thermal_sample(i,&raw) && !mt6762_pmic_temperature(&cal,i,raw,&mc);
        publish(i,ok,mc,acquired,expires);
    }
}
static void sample_cpu(void)
{
    const unsigned offsets[5]={0x90,0x94,0x98,0x190,0x194};
    struct mt6762_cpu_cal cal;
    uint32_t a[3],b[3];
    uint64_t acquired,expires;
    int valid=sample_window(&acquired,&expires),mc=0;
    for(unsigned i=0;valid && i<3;i++)a[i]=reg32(efuse,i*4);
    for(unsigned i=0;valid && i<3;i++) {b[i]=reg32(efuse,i*4);if(a[i]!=b[i])valid=0;}
    if(valid && mt6762_cpu_cal_decode(a,&cal))valid=0;
    /* Admission additionally promises initialized sensor routing/clocking.
     * Runtime checks reject disabled/paused banks; no register is changed. */
    for(unsigned i=0;i<5;i++) {
        unsigned bank=i<3?0:0x100,mask=i<3?7:3;
        int enabled=valid && (reg32(controller,bank)&mask)==mask && !(reg32(controller,bank+0x3c)&0x10e);
        unsigned raw=enabled ? reg32(controller,offsets[i])&4095 : 0;
        int ok=valid && enabled && !mt6762_cpu_temperature(&cal,i,raw,&mc);
        publish(i+3,ok,mc,acquired,expires);
    }
}
#ifndef MT6762_THERMAL_HOST_TEST
static void worker(__unused void *parameter,__unused wait_result_t result)
{
    for(;;) {
        if(pmic_enabled)sample_pmic();
        if(cpu_enabled)sample_cpu();
        delay_for_interval(500,NSEC_PER_MSEC);
    }
}
void mt6762_thermal_init(void)
{
    thread_t thread;
    if(started || !mt6762_platform_ready())return;
    started=1;
    pmic_enabled=flag("pmic-thermal-adc-owned");
    if(flag("cpu-thermal-observe-verified")) {
        controller=(uintptr_t)mt6762_map_mmio(0x1100b000,0x1000);
        efuse=(uintptr_t)mt6762_map_mmio(0x11c50190,12);
        cpu_enabled=controller && efuse;
    }
    if(!pmic_enabled && !cpu_enabled)return;
    printf("MT6762 thermal: observation enabled PMIC=%d CPU=%d; CPU freshness and DVFS policy unavailable\n",pmic_enabled,cpu_enabled);
    if(kernel_thread_start(worker,NULL,&thread)==KERN_SUCCESS)thread_deallocate(thread);
}
#endif
