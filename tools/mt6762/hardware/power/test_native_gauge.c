#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../../../bsd/dev/mt6762_gauge_protocol.h"
#include "gauge_vectors.h"
struct fake {unsigned reads,writes,delays,fault;uint16_t control;};
static int rd(void *p,uint16_t r,uint16_t *v)
{
 struct fake *f=p;f->reads++;
 if(f->fault==5)return -1;
 if(r==0xc0c)*v=f->fault==1?0x18:0;
 else if(r==0xd08)*v=1;
 else if(r==0xd0a)*v=f->control;
 else if(r==0xd8a)*v=100;
 else if(r==0xd12)*v=0;
 else if(r==0xd14)*v=1;
 else if(r==0xd20)*v=10;
 else if(r==0xd22||r==0xd24)*v=0;
 else assert(0);
 return 0;
}
static int wr(void *p,uint16_t r,uint16_t v)
{
 struct fake *f=p;f->writes++;assert(r==0xd0a);assert(!(v&0x1f06));
 if(f->fault==6)return -1;
 f->control=v;
 if((v&1) && f->fault!=3)f->control|=0x8000;
 if((v&8) && f->fault==4)f->control|=0x8000;
 return 0;
}
static void wait(void *p,unsigned us) {struct fake *f=p;assert(us==10);f->delays++;}
int main(void)
{
 for(unsigned i=0;i<sizeof(gauge_vectors)/sizeof(gauge_vectors[0]);i++) {
  const long long *v=gauge_vectors[i];int ua;int64_t uah;
  assert(!mt6762_gauge_current((uint16_t)v[0],(unsigned)v[3],(unsigned)v[4],&ua) && ua==v[5]);
  assert(!mt6762_gauge_charge((uint16_t)v[1],(uint16_t)v[2],(unsigned)v[3],(unsigned)v[4],&uah) && uah==v[6]);
 }
 for(unsigned fault=0;fault<7;fault++) {
  struct fake f={.fault=fault,.control=fault==2?0x8000:0};
  struct mt6762_gauge_transport t={.io={&f,rd,wr,wait}};
  struct mt6762_gauge_snapshot s={.current=1234},old=s;
  int e=mt6762_gauge_capture(&t,&s);
  if(!fault)assert(!e && s.current==100 && s.ticks==10 && f.writes==4 && !f.control);
  else {
   assert(e && t.fault && !memcmp(&s,&old,sizeof(s)));
   if(fault==1||fault==2||fault==5)assert(!f.writes);
   unsigned reads=f.reads,writes=f.writes;
   assert(mt6762_gauge_capture(&t,&s) && f.reads==reads && f.writes==writes);
  }
  assert(f.delays<=1000);
 }
 assert(!mt6762_gauge_progress(1,1));assert(mt6762_gauge_progress(1,2));
 assert(!mt6762_gauge_progress(1000,1));assert(mt6762_gauge_progress((1ull<<33)-1,0));
 int ua=123;assert(mt6762_gauge_current(100,0,1000,&ua) && ua==123);
 puts("native gauge original-code arithmetic/latch/freshness tests: PASS");
}
