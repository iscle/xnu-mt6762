/* Compile the native consumer, controlling only its clock and hardware I/O. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define MT6762_THERMAL_HOST_TEST 1
#define NSEC_PER_MSEC 1000000
#define LCK_GRP_DECLARE(name,label) int name __attribute__((unused))
#define LCK_MTX_DECLARE(name,group) int name
static uint64_t now,read_delay,conversion_delay,lock_wait,interval_delay,duration;
static unsigned reads,conversions,fail_read,fail_conversion;
static const uint16_t pmic_words[]={0x137,1588,0,0,1526,1534};
static const uint32_t cpu_words[]={0x0299546b,0x9d9d514c,0xa5d36940};
static void lck_mtx_lock(int *lock)
{assert(!*lock);*lock=1;now+=lock_wait;lock_wait=0;}
static void lck_mtx_unlock(int *lock){assert(*lock);*lock=0;}
static void clock_get_uptime(uint64_t *value){*value=now;}
static void clock_interval_to_absolutetime_interval(unsigned ms,unsigned scale,uint64_t *value)
{assert(ms==2000 && scale==NSEC_PER_MSEC);now+=interval_delay;*value=duration;}
static int mt6762_pwrap_read16(uint16_t reg,uint16_t *value)
{
    reads++;now+=read_delay;
    if(reads==fail_read)return -EIO;
    if(reg==8)*value=0x5730;
    else {assert(reg>=0x11ae && reg<=0x11b8 && !(reg&1));*value=pmic_words[(reg-0x11ae)/2];}
    return 0;
}
static int mt6762_pmic_thermal_sample(unsigned sensor,uint16_t *value)
{
    assert(sensor<3);conversions++;now+=conversion_delay;
    if(conversions==fail_conversion)return -EIO;
    *value=pmic_words[sensor? sensor+3:1];return 0;
}
static uint32_t reg32(uintptr_t base,unsigned offset)
{
    reads++;now+=read_delay;
    if(base==2){assert(offset<=8 && !(offset&3));return cpu_words[offset/4];}
    assert(base==1);
    if(offset==0)return 7;
    if(offset==0x100)return 3;
    if(offset==0x3c || offset==0x13c)return 0;
    assert(offset==0x90 || offset==0x94 || offset==0x98 || offset==0x190 || offset==0x194);
    return 3682;
}
#include "../../../../bsd/dev/mt6762_thermal.c"
static void reset(void)
{
    now=100;read_delay=conversion_delay=lock_wait=interval_delay=0;duration=2000;
    reads=conversions=fail_read=fail_conversion=0;errors=samples=observed_mask=0;
    controller=1;efuse=2;
    memset(acquisitions,0,sizeof(acquisitions));memset(deadlines,0,sizeof(deadlines));
}
static void rejected(unsigned sensor)
{
    int value=12345;
    assert(mt6762_pmic_temperature_read(sensor,&value)==-ENXIO && value==12345);
}
int main(void)
{
    reset();sample_pmic();sample_cpu();assert(valid_mask(now)==255);
    int value=0;assert(!mt6762_pmic_temperature_read(0,&value) && value==27500);
    now=2099;assert(valid_mask(now)==255);now=2100;assert(valid_mask(now)==0);rejected(0);
    /* Calibration latency counts, even if the eventual conversion succeeds. */
    reset();read_delay=160;sample_pmic();assert(!valid_mask(now) && !samples && errors==3);
    /* Each later sensor shares the calibration's acquisition start. */
    reset();conversion_delay=700;sample_pmic();assert(samples==2 && errors==1);
    assert(deadlines[0]==2100 && deadlines[1]==2100 && !deadlines[2]);
    assert(!valid_mask(now));rejected(0);rejected(2);
    /* Preemption during interval conversion cannot renew the lease. */
    reset();interval_delay=3000;sample_pmic();assert(!samples && errors==3);rejected(0);
    reset();interval_delay=100;sample_pmic();assert(samples==3 && deadlines[0]==2100);
    /* Contention after acquisition must be included at publication and read. */
    reset();lock_wait=2000;sample_pmic();assert(!samples && errors==3);rejected(0);
    reset();sample_pmic();lock_wait=2000;rejected(0);
    /* Reject arithmetic overflow/zero duration without touching hardware. */
    reset();now=UINT64_MAX-10;sample_pmic();assert(!reads && !conversions && !samples);
    reset();duration=0;sample_cpu();assert(!reads && !samples && errors==5);
    /* Clock regression cannot resurrect a value predating acquisition. */
    reset();sample_pmic();now=99;assert(!valid_mask(now));rejected(0);
    /* A failed replacement invalidates its previous value, independent of age. */
    reset();sample_pmic();fail_conversion=4;sample_pmic();rejected(0);
    assert(valid_mask(now)==6);
    reset();sample_pmic();fail_read=reads+1;sample_pmic();assert(!valid_mask(now));
    /* CPU observations retain the same bounded cache age, without asserting
     * that the hardware performed a new sensor conversion. */
    reset();read_delay=100;sample_cpu();assert(samples==4 && errors==1);
    assert(!valid_mask(now));
    assert(mt6762_pmic_temperature_read(3,&value)==-EINVAL);
    assert(mt6762_pmic_temperature_read(0,NULL)==-EINVAL);
    puts("native thermal consumer acquisition/expiry/failure tests: PASS");
}
