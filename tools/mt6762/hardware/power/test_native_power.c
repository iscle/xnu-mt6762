/* Exercises the exact header used by bsd/dev/mt6762_power.c. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../../../bsd/dev/mt6762_power_protocol.h"
#define INIT (1u << 21)
struct mock { uint32_t states[8],offset[8],value[8]; unsigned n,index,reads,writes,delay; };
static uint32_t rd(void *p,uint32_t off)
{
    struct mock *m=p;assert(off==0xc24);m->reads++;
    unsigned i=m->index<m->n ? m->index++ : m->n-1;
    return m->states[i];
}
static void wr(void *p,uint32_t off,uint32_t v)
{struct mock *m=p;assert(m->writes<8);m->offset[m->writes]=off;m->value[m->writes++]=v;}
static void wait_us(void *p,unsigned us) {((struct mock *)p)->delay+=us;}
static void wacs_tests(void)
{
    struct mock m={.states={INIT,INIT|(2u<<16),INIT|(6u<<16)|0xbeef,INIT},.n=4};
    struct mt6762_wacs_io io={&m,rd,wr,wait_us};uint16_t v=0x1234;
    assert(!mt6762_wacs_transfer(&io,0,0x24,&v));assert(v==0xbeef);
    assert(m.writes==2 && m.offset[0]==0xc20 && m.value[0]==0x00120000);
    assert(m.offset[1]==0xc28 && m.value[1]==1 && m.delay==10);
    m=(struct mock){.states={INIT,INIT|(2u<<16),INIT},.n=3};v=0xabcd;
    assert(!mt6762_wacs_transfer(&io,1,0x110e,&v));
    assert(m.writes==1 && m.value[0]==0x8887abcd && v==0xabcd);
    m=(struct mock){.states={0},.n=1};v=0x1234;
    assert(mt6762_wacs_transfer(&io,0,8,&v)==-2 && !m.writes && v==0x1234);
    m=(struct mock){.states={INIT|(2u<<16)},.n=1};
    assert(mt6762_wacs_transfer(&io,0,8,&v)==-3 && !m.writes);
    assert(m.reads==1000 && m.delay==10000 && v==0x1234);
    m=(struct mock){.states={INIT,INIT|(2u<<16)},.n=2};
    assert(mt6762_wacs_transfer(&io,0,8,&v)==-3 && m.writes==1 && v==0x1234);
    m=(struct mock){.states={INIT,INIT|(6u<<16)|0x5730,INIT|(2u<<16)},.n=3};
    assert(mt6762_wacs_transfer(&io,0,8,&v)==-3 && m.writes==2 && v==0x1234);
    m=(struct mock){.states={INIT},.n=1};
    assert(mt6762_wacs_transfer(&io,0,7,&v)==-1 && !m.reads && !m.writes);
    assert(mt6762_wacs_transfer(NULL,0,8,&v)==-1);
}
struct adc { uint16_t out,request,address; unsigned reads,writes,delay,pending; int re,we; };
static int adc_rd(void *p,uint16_t address,uint16_t *v)
{struct adc *a=p;assert(address==a->address);a->reads++;if(a->re)return a->re;*v=a->reads<=a->pending?0:a->out;return 0;}
static int adc_wr(void *p,uint16_t address,uint16_t v)
{struct adc *a=p;assert(address==0x110e);a->request=v;a->writes++;return a->we;}
static void adc_delay(void *p,unsigned us) {((struct adc *)p)->delay+=us;}
static void adc_tests(void)
{
    struct adc a={.out=0x8000|26700,.address=0x108a,.pending=2};
    struct mt6762_adc_io io={&a,adc_rd,adc_wr,adc_delay};int mv=-1;
    assert(!mt6762_adc_sample(&io,1,&mv));
    assert(mv==4400 && a.request==2 && a.reads==3 && a.delay==1680);
    a=(struct adc){.out=0x8000|1400,.address=0x108e};
    assert(!mt6762_adc_sample(&io,3,&mv));assert(mv==615 && a.request==8 && a.delay==80);
    a=(struct adc){.out=0,.address=0x108e};mv=777;
    assert(mt6762_adc_sample(&io,3,&mv)==-3 && mv==777 && a.reads==160);
    a=(struct adc){.out=0x8000,.address=0x108e};
    assert(mt6762_adc_sample(&io,3,&mv)==-4 && mv==777);
    a=(struct adc){.out=0x8fff,.address=0x108e};
    assert(mt6762_adc_sample(&io,3,&mv)==-4 && mv==777);
    a=(struct adc){.address=0x108e,.we=-9};
    assert(mt6762_adc_sample(&io,3,&mv)==-9 && !a.reads && mv==777);
    a=(struct adc){.address=0x108e,.re=-8};
    assert(mt6762_adc_sample(&io,3,&mv)==-8 && mv==777);
    a=(struct adc){0};assert(mt6762_adc_sample(&io,11,&mv)==-1 && !a.writes);
}
static void keys_tests(void)
{
    struct mt6762_key_filter k={0};
    for(unsigned i=0;i<10;i++)assert(!mt6762_key_update(&k,1,1)); /* held across handoff */
    assert(!mt6762_key_update(&k,1,0));
    assert(!mt6762_key_update(&k,1,1));assert(!mt6762_key_update(&k,1,0));
    assert(!mt6762_key_update(&k,1,1));assert(mt6762_key_update(&k,1,1)==1);
    assert(!mt6762_key_update(&k,1,1));
    assert(!mt6762_key_update(&k,1,0));assert(mt6762_key_update(&k,1,0)==-1);
    assert(!mt6762_key_update(&k,1,1));assert(mt6762_key_update(&k,1,1)==1);
    assert(mt6762_key_update(&k,0,0)==-1);assert(!mt6762_key_update(&k,0,0));
    assert(!mt6762_key_update(&k,1,1));assert(!mt6762_key_update(&k,1,1));
    assert(!mt6762_key_update(&k,1,0));assert(!mt6762_key_update(&k,1,1));
    assert(mt6762_key_update(&k,1,1)==1);
}
int main(void) {wacs_tests();adc_tests();keys_tests();puts("native PWRAP, ADC and button tests: PASS");return 0;}
