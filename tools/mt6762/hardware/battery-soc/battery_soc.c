#include "battery_soc.h"
#include "profile_sha256.h"
#define PROFILE_MARKER 0x42535031U
#define ALL_QUALITY 63U
static void zero(void *p,size_t n) {unsigned char *v=p;while(n--)*v++=0;}
static uint32_t be32(const unsigned char *p) {return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}
static int digest_equal(const unsigned char *a,const unsigned char *b) {unsigned i,v=0;for(i=0;i<32;i++)v|=a[i]^b[i];return v==0;}
static int64_t floor_div(int64_t n,int64_t d) {int64_t q=n/d,r=n%d;return q-(r<0);}
static int64_t ceil_div(int64_t n,int64_t d) {int64_t q=n/d,r=n%d;return q+(r>0);}
static int64_t magnitude(int64_t n) {return n<0?-n:n;}
int bs_profile_init(struct bs_profile *p,const struct bs_blob b[6],const uint32_t rows[6],const uint32_t cols[6],const int32_t temps[6],const struct bs_coefficients *coeff) {
 static const int32_t expected_t[6]={50,25,10,0,-6,-10};
 static const unsigned char hashes[2][32]={
 {0xd4,0xd4,0x00,0x34,0xe8,0x60,0x47,0xa4,0x23,0x18,0xbc,0xdc,0xea,0xb4,0x1e,0x25,0x6e,0x90,0x3d,0xa4,0xf1,0x9e,0x79,0x47,0xec,0xf8,0xbe,0xc0,0x83,0x7f,0xa5,0xcf},
 {0xb8,0x78,0xee,0xcf,0x85,0x15,0xac,0x02,0xa2,0x5b,0x52,0x6c,0xcd,0xcf,0x1d,0xaf,0x92,0x6d,0x95,0x47,0xe8,0xff,0xf8,0x75,0xc3,0x58,0xe0,0x82,0xd0,0x2c,0xa5,0x8d}};
 unsigned t,i;unsigned char digest[32];
 if(!p)return BS_ARGUMENT;
 zero(p,sizeof(*p));
 if(!b||!rows||!cols||!temps||!coeff)return BS_ARGUMENT;
 if(coeff->rfg_dt!=10||coeff->car_tune_dt!=100||coeff->meter_resistance_dt!=75)return BS_PROFILE;
 /* Verify all byte inputs before exposing any decoded profile. */
 for(t=0;t<6;t++) {
  if(!b[t].bytes||b[t].length!=BS_PROFILE_BYTES||rows[t]!=100||cols[t]!=3||temps[t]!=expected_t[t])return BS_PROFILE;
  bs_sha256(b[t].bytes,b[t].length,digest);
 if(!digest_equal(digest,hashes[t<3?0:1]))return BS_PROFILE;
 }
 p->resistance_min_0p1mohm=UINT32_MAX;
 for(t=0;t<6;t++)for(i=0;i<BS_ROWS;i++) {
  const unsigned char *v=b[t].bytes+i*12;struct bs_row *r=&p->rows[t][i];
  r->charge_0p1mah=be32(v);r->voltage_0p1mv=be32(v+4);r->resistance_0p1mohm=be32(v+8);
  if(r->resistance_0p1mohm<p->resistance_min_0p1mohm)p->resistance_min_0p1mohm=r->resistance_0p1mohm;
  if(r->resistance_0p1mohm>p->resistance_max_0p1mohm)p->resistance_max_0p1mohm=r->resistance_0p1mohm;
 }
 p->initialized=PROFILE_MARKER;return BS_OK;
}
static void include_charge(int64_t q_floor,int64_t q_ceil,int64_t *low,int64_t *high) {
 if(q_floor<*low)*low=q_floor;
 if(q_ceil>*high)*high=q_ceil;
}
int bs_ocv_interval(const struct bs_profile *p,int64_t lo,int64_t hi,struct bs_result *out) {
 unsigned t,i;int64_t qlo=INT64_MAX,qhi=INT64_MIN;
 if(!out)return BS_ARGUMENT;
 zero(out,sizeof(*out));
 if(!p||p->initialized!=PROFILE_MARKER)return BS_PROFILE;
 if(lo<2500000||hi>5000000||lo>hi)return BS_RANGE;
 for(t=0;t<6;t++) {
  const struct bs_row *r=p->rows[t];int64_t top=(int64_t)r[0].voltage_0p1mv*100,bottom=(int64_t)r[BS_ROWS-1].voltage_0p1mv*100;
  if(hi>=top)include_charge(0,0,&qlo,&qhi);
  if(lo<=bottom)include_charge(BS_MODEL_CAPACITY_UAH,BS_MODEL_CAPACITY_UAH,&qlo,&qhi);
  for(i=1;i<BS_ROWS;i++) {
   int64_t va=(int64_t)r[i-1].voltage_0p1mv*100,vb=(int64_t)r[i].voltage_0p1mv*100;
   int64_t qa=(int64_t)r[i-1].charge_0p1mah*100,qb=(int64_t)r[i].charge_0p1mah*100;
   int64_t minv=va<vb?va:vb,maxv=va>vb?va:vb,x,y;
   if(hi<minv||lo>maxv)continue;
   if(va==vb) {include_charge(qa<qb?qa:qb,qa>qb?qa:qb,&qlo,&qhi);continue;}
   /* Normalize denominator positive; preserve both direction reversals. */
   if(va>vb) {int64_t z=va;va=vb;vb=z;z=qa;qa=qb;qb=z;}
   x=lo>va?lo:va;y=hi<vb?hi:vb;
   include_charge(qa+floor_div((qb-qa)*(x-va),vb-va),qa+ceil_div((qb-qa)*(x-va),vb-va),&qlo,&qhi);
   include_charge(qa+floor_div((qb-qa)*(y-va),vb-va),qa+ceil_div((qb-qa)*(y-va),vb-va),&qlo,&qhi);
  }
 }
 if(qlo<0||qhi>BS_MODEL_CAPACITY_UAH||qlo>qhi)return BS_RANGE;
 out->lower_bp=(uint32_t)floor_div((BS_MODEL_CAPACITY_UAH-qhi)*10000,BS_MODEL_CAPACITY_UAH);
 out->upper_bp=(uint32_t)ceil_div((BS_MODEL_CAPACITY_UAH-qlo)*10000,BS_MODEL_CAPACITY_UAH);
 out->quality=ALL_QUALITY & ~BS_CONDITIONAL_IR_MODEL;out->conditional_ocv_lower_uv=lo;out->conditional_ocv_upper_uv=hi;
 /* No valid flag: arithmetic alone is not a fresh observable estimate. */
 return BS_OK;
}
static int fail(struct bs_state *s,int error) {s->phase=BS_FAILED;s->fault=error;
 zero(&s->last,sizeof(s->last));return error;}
int bs_begin(struct bs_state *s,unsigned enabled) {
 if(!s)return BS_ARGUMENT;
 zero(s,sizeof(*s));
 if(enabled!=1)return BS_DISABLED;
 s->phase=BS_WAIT_FIRST;return BS_OK;
}
static int sample_ok(const struct bs_sample *v,uint64_t now) {
 if(!v||v->valid!=7||!v->sequence||!v->generation)return BS_ARGUMENT;
 if(v->acquired_us>now||v->expires_us<=v->acquired_us||v->expires_us-v->acquired_us>BS_MAX_LEASE_US||now>=v->expires_us)return BS_STALE;
 if(v->nter_ticks>=(UINT64_C(1)<<33)||v->charge_uah>INT64_C(20000000)||v->charge_uah<INT64_C(-20000000)||v->charge_uah%100)return BS_COUNTER;
 if(v->voltage_uv<2500000||v->voltage_uv>5000000||v->current_ua>BS_MAX_CURRENT_UA||v->current_ua<-BS_MAX_CURRENT_UA||v->current_ua%100||v->voltage_uv%1000)return BS_RANGE;
 return BS_OK;
}
int bs_update(struct bs_state *s,const struct bs_profile *p,const struct bs_sample *v,uint64_t now,struct bs_result *out) {
 int e;int64_t delta,limit,span,lo,hi,ir1,ir2;uint64_t dt,ticks;
 if(!out)return BS_ARGUMENT;
 zero(out,sizeof(*out));
 if(!s)return BS_ARGUMENT;
 if(s->phase==BS_OFF)return BS_DISABLED;
 if(s->phase==BS_FAILED)return BS_FAULT;
 if(now<s->last_now_us)return fail(s,BS_TIME);
 s->last_now_us=now;
 if(!p||p->initialized!=PROFILE_MARKER)return fail(s,BS_PROFILE);
 e=sample_ok(v,now);
 if(e)return fail(s,e);
 if(s->phase==BS_WAIT_FIRST) {s->previous=*v;s->phase=BS_WAIT_SECOND;return BS_PENDING;}
 if(v->generation!=s->previous.generation||v->sequence<=s->previous.sequence)return fail(s,BS_COUNTER);
 if(v->acquired_us<=s->previous.acquired_us)return fail(s,BS_TIME);
 dt=v->acquired_us-s->previous.acquired_us;
 if(dt>BS_MAX_GAP_US)return fail(s,BS_TIME);
 ticks=(v->nter_ticks-s->previous.nter_ticks)&((UINT64_C(1)<<33)-1);
 if(!ticks||ticks>=(UINT64_C(1)<<32))return fail(s,BS_COUNTER);
 /* Original decoded charge is0.1mAh-quantized. Bound by global allowed2A
  * during the whole gap, rather than assuming endpoints bound transient load. */
 delta=v->charge_uah-s->previous.charge_uah;
 limit=ceil_div((int64_t)BS_MAX_CURRENT_UA*(int64_t)dt,INT64_C(3600000000))+BS_CAR_TOLERANCE_UAH;
 if(magnitude(delta)>limit)return fail(s,BS_JUMP);
 if((s->previous.current_ua>0&&v->current_ua>0&&delta < -BS_CAR_TOLERANCE_UAH)||
    (s->previous.current_ua<0&&v->current_ua<0&&delta > BS_CAR_TOLERANCE_UAH))return fail(s,BS_DIRECTION);
 if(s->phase==BS_WAIT_SECOND) {
  /* Conditional stock resistance model: R_FG100 + FG_METER_RESISTANCE75
   * (0.1mOhm) plus the full actual table R envelope. Positive current charges,
   * so terminal voltage is higher than conditional OCV. No measured-temp claim.
   * Rounding outward and ±1mV account only for arithmetic ADC millivolt flooring.
   * This is NOT a bound on unknown physical calibration/hysteresis/model error. */
  ir1=(int64_t)v->current_ua*(p->resistance_min_0p1mohm+175);
  ir2=(int64_t)v->current_ua*(p->resistance_max_0p1mohm+175);
  if(ir1>ir2) {int64_t z=ir1;ir1=ir2;ir2=z;}
  lo=(int64_t)v->voltage_uv-ceil_div(ir2,10000)-1000;
  hi=(int64_t)v->voltage_uv-floor_div(ir1,10000)+1000;
  e=bs_ocv_interval(p,lo,hi,out);
 if(e)return fail(s,e);
  s->seed_charge_uah=v->charge_uah;s->seed_lower_bp=out->lower_bp;s->seed_upper_bp=out->upper_bp;
  s->phase=BS_TRACKING;out->quality=ALL_QUALITY;out->ocv_acquired_us=v->acquired_us;
 } else if(s->phase==BS_TRACKING) {
  span=v->charge_uah-s->seed_charge_uah;
  lo=(int64_t)s->seed_lower_bp*BS_MODEL_CAPACITY_UAH+(span-BS_CAR_TOLERANCE_UAH)*10000;
  hi=(int64_t)s->seed_upper_bp*BS_MODEL_CAPACITY_UAH+(span+BS_CAR_TOLERANCE_UAH)*10000;
  if(lo<0||hi>10000*BS_MODEL_CAPACITY_UAH)return fail(s,BS_RANGE);
  *out=s->last;out->lower_bp=(uint32_t)floor_div(lo,BS_MODEL_CAPACITY_UAH);out->upper_bp=(uint32_t)ceil_div(hi,BS_MODEL_CAPACITY_UAH);
 } else return fail(s,BS_ARGUMENT);
 out->valid=1;out->acquired_us=v->acquired_us;out->expires_us=v->expires_us;
 s->previous=*v;s->last=*out;return BS_OK;
}
int bs_read(struct bs_state *s,uint64_t now,struct bs_result *out) {
 if(!out)return BS_ARGUMENT;
 zero(out,sizeof(*out));
 if(!s)return BS_ARGUMENT;
 if(s->phase==BS_FAILED)return BS_FAULT;
 if(s->phase==BS_OFF)return BS_DISABLED;
 if(now<s->last_now_us)return fail(s,BS_TIME);
 s->last_now_us=now;
 if(s->phase!=BS_TRACKING)return BS_PENDING;
 if(now<s->last.acquired_us)return fail(s,BS_TIME);
 if(now>=s->last.expires_us)return fail(s,BS_STALE);
 *out=s->last;return BS_OK;
}
