/* Exercise the real native observer and getters with controlled PMIC/time I/O. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define MT6762_GAUGE_HOST_TEST 1
#define NSEC_PER_MSEC 1000000
#define LCK_GRP_DECLARE(name,text) int name __attribute__((unused))
#define LCK_MTX_DECLARE(name,group) int name
static uint64_t test_now,lock_wait,read_delay,interval_preemption;
static unsigned reads,writes,fail_at;
static uint16_t control,fixture_current,fixture_low,fixture_high;
static uint64_t fixture_ticks;
static int changed_calibration;
static void lck_mtx_lock(int *m){assert(!*m);*m=1;test_now+=lock_wait;lock_wait=0;}
static void lck_mtx_unlock(int *m){assert(*m);*m=0;}
static void clock_get_uptime(uint64_t *v){*v=test_now;}
static void clock_interval_to_absolutetime_interval(unsigned ms,unsigned scale,uint64_t *v)
{assert(scale==NSEC_PER_MSEC);test_now+=interval_preemption;*v=ms;}
static int mt6762_pwrap_read16(uint16_t reg,uint16_t *v)
{
 reads++;test_now+=read_delay;
 if(reads==fail_at)return -1;
 switch(reg) {
 case 8:*v=0x5730;break;
 case 0xd08:*v=0x29;break;
 case 0xc8e:*v=4096;break;
 case 0xc90:case 0xd94:case 0xc0c:*v=0;break;
 case 0xd96:*v=changed_calibration?4095:4096;break;
 case 0xd0a:*v=control;break;
 case 0xd8a:*v=fixture_current;break;
 case 0xd12:*v=fixture_low;break;
 case 0xd14:*v=fixture_high;break;
 case 0xd20:*v=fixture_ticks;break;
 case 0xd22:*v=fixture_ticks>>16;break;
 case 0xd24:*v=fixture_ticks>>32;break;
 default:assert(0);
 }return 0;
}
#include "../../../../bsd/dev/mt6762_gauge.c"
static int fake_read(void *p,uint16_t reg,uint16_t *v)
{(void)p;return mt6762_pwrap_read16(reg,v);}
static int fake_write(void *p,uint16_t reg,uint16_t v)
{
 (void)p;assert(reg==0xd0a);writes++;
 assert(v==1 || v==9 || v==8 || v==0);
 control=v|(v&1?0x8000:0);return 0;
}
static void fake_delay(void *p,unsigned us){(void)p;assert(us==10);}
static void reset(void)
{
 test_now=100;lock_wait=read_delay=interval_preemption=0;reads=writes=fail_at=0;control=0;
 fixture_current=100;fixture_low=0;fixture_high=100;fixture_ticks=10;
 changed_calibration=0;valid=errors=samples=transport_fault=freshness_rejections=0;
 raw_current=-1;have_ticks=0;last_ticks=0;memset(&observation,0,sizeof(observation));
 transport=(struct mt6762_gauge_transport){.io={NULL,fake_read,fake_write,fake_delay}};
 rfg=100;tune=1000;
 uint16_t calibration[]={0x29,4096,0,0,4096};memcpy(expected,calibration,sizeof(expected));
}
static void fresh_pair(void)
{observe();assert(!valid);fixture_ticks++;test_now+=10;observe();assert(valid);}
int main(void)
{
 struct gauge_observation out,untouched;
 reset();memset(&out,0xa5,sizeof(out));untouched=out;
 observe();assert(!valid && observation_read(&out)==-ENXIO && !memcmp(&out,&untouched,sizeof(out)));
 fixture_ticks++;test_now+=10;observe();assert(!observation_read(&out));
 int64_t independent;assert(!mt6762_gauge_charge(0,100,100,1000,&independent));
 assert(out.current_ua==31400 && out.charge_uah==independent && out.charge_uah>0);
 assert(out.acquired_abs==110 && out.expires_abs==2110);
 /* Both signs come from one completed latch, never mixed with the prior pair. */
 fixture_ticks++;fixture_current=0xff9b;fixture_high=0xff9b;fixture_low=0xf800;
 observe();assert(!observation_read(&out));assert(out.current_ua==-31400 && out.charge_uah<0);
 /* Legitimate zero is valid and distinguishable from an unavailable counter. */
 fixture_ticks++;fixture_current=0xffff;fixture_low=fixture_high=0;
 observe();assert(!observation_read(&out) && !out.current_ua && !out.charge_uah);
 /* A partial CAR read must invalidate the whole old pair, then stay faulted. */
 fixture_ticks++;fail_at=reads+12;observe();assert(!valid && transport.fault);
 unsigned old_reads=reads,old_writes=writes;observe();assert(reads==old_reads && writes==old_writes);
 assert(observation_read(&out)==-ENXIO);
 reset();fresh_pair();fixture_ticks++;changed_calibration=1;observe();assert(!valid && transport_fault);
 reset();fresh_pair();observe();assert(!valid && freshness_rejections==1 && !transport_fault);
 fixture_ticks++;observe();assert(valid); /* Fresh progression can recover from a stationary counter. */
 reset();fresh_pair();fixture_ticks--;observe();assert(!valid && transport_fault);
 reset();fixture_ticks=(1ull<<33)-1;observe();fixture_ticks=0;observe();assert(valid);
 /* Slow acquisition keeps the start deadline; it cannot gain a new lease. */
 reset();observe();fixture_ticks++;read_delay=100;observe();assert(!valid && freshness_rejections==1);
 assert(!transport_fault);read_delay=0;fixture_ticks++;observe();assert(valid);
 reset();observe();fixture_ticks++;read_delay=10;uint64_t start=test_now;observe();
 assert(!observation_read(&out) && out.acquired_abs==start && out.expires_abs==start+2000);
 test_now=out.expires_abs-1;assert(!observation_read(&out));
 test_now=out.expires_abs;assert(observation_read(&out)==-ENXIO);
 /* Preemption after acquired_abs must not move the deadline's origin. */
 reset();observe();fixture_ticks++;interval_preemption=3000;observe();
 assert(!valid && freshness_rejections==1 && !transport_fault);
 interval_preemption=0;fixture_ticks++;observe();assert(valid);
 reset();observe();fixture_ticks++;interval_preemption=100;start=test_now;observe();
 assert(!observation_read(&out) && out.acquired_abs==start && out.expires_abs==start+2000);
 /* Checked absolute deadline overflow rejects before issuing PMIC requests. */
 reset();test_now=UINT64_MAX-1000;observe();assert(!valid && !reads && !writes);
 assert(freshness_rejections==1 && !transport_fault);
 /* A blocked reader checks time after acquiring its lock. */
 reset();fresh_pair();test_now=observation.expires_abs-1;lock_wait=2;
 assert(observation_read(&out)==-ENXIO);
 int ua=123;uint64_t expires=456;
 assert(mt6762_gauge_current_snapshot(&ua,&expires)==-ENXIO && ua==123 && expires==456);
 assert(observation_read(NULL)==-EINVAL);
 puts("native coherent gauge observer: signs/zero/latch/calibration/NTER/acquisition expiry/lock wait PASS");
}
