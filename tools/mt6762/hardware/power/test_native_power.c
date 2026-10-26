/* Exercises the exact header used by bsd/dev/mt6762_power.c. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../../../bsd/dev/mt6762_power_protocol.h"
#include "mt6762_pwrap_entry.h"
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
    for(unsigned profile=1;profile<=2;profile++)for(unsigned bits=0;bits<4;bits++) {
        uint32_t init=bits<<21;v=0x1234;
        m=(struct mock){.states={init,init|(6u<<16)|0x5730,init},.n=3};
        int error=mt6762_wacs_transfer_profile(&io,profile,0,8,&v);
        if(bits&(1u<<(profile-1))) {
            assert(!error && v==0x5730 && m.writes==2);
            assert(m.offset[0]==0xc20 && m.value[0]==0x40000);
            assert(m.offset[1]==0xc28 && m.value[1]==1);
        } else assert(error==-2 && v==0x1234 && !m.writes && m.reads==1);
    }
    m=(struct mock){.states={3u<<21},.n=1};v=0x1234;
    assert(mt6762_wacs_transfer_profile(&io,0,0,8,&v)==-1 && !m.reads && !m.writes);
    assert(mt6762_wacs_transfer_profile(&io,3,0,8,&v)==-1 && !m.reads && !m.writes);
    for(unsigned phase=0;phase<3;phase++) {
        uint32_t init=1u<<22;
        m=(struct mock){.states={init,init|(6u<<16)|0x5730,init|(2u<<16)},.n=3};
        if(!phase)m=(struct mock){.states={init|(6u<<16)},.n=1};
        if(phase==1)m=(struct mock){.states={init,init|(2u<<16)},.n=2};
        assert(mt6762_wacs_transfer_profile(&io,2,0,8,&v)==-3);
        assert(v==0x1234 && m.writes==phase);
    }
}
struct entry_mock {uint32_t bad_address,bad_value;unsigned reads;};
static uint32_t entry_rd(void *ctx,uint32_t a)
{
    struct entry_mock *m=ctx;m->reads++;
    if(a==m->bad_address)return m->bad_value;
    switch(a) {
    case 0x10001090:case 0x1000d000:case 0x1000d07c:return 0;
    case 0x1000d004:case 0x1000d09c:case 0x1000d0a0:return 1;
    case 0x1000dc24:return 0x80f00800; /* actual capture17 */
    default:assert(0);return 0;
    }
}
static void entry_tests(void)
{
    struct entry_mock m={0};assert(mt6762_pwrap_entry_ok(entry_rd,&m));assert(m.reads==14);
    const uint32_t bad[][2]={{0x10001090,2},{0x1000d000,1},{0x1000d004,0},
        {0x1000d07c,1},{0x1000d09c,0},{0x1000d0a0,0},
        {0x1000dc24,1u<<21},{0x1000dc24,0x460000},{0x1000dc24,0x420000}};
    for(unsigned n=0;n<sizeof(bad)/sizeof(bad[0]);n++) {
        m=(struct entry_mock){bad[n][0],bad[n][1],0};
        assert(!mt6762_pwrap_entry_ok(entry_rd,&m));
        if(!n)assert(m.reads==1);
    }
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
    assert(mv==4400 && a.request==2 && a.reads==3 && a.delay==1480);
    a=(struct adc){.out=0x8000|1400,.address=0x108e,.pending=1};
    assert(!mt6762_adc_sample(&io,3,&mv));assert(mv==615 && a.request==8 && a.delay==80);
    a=(struct adc){.out=0,.address=0x108e};mv=777;
    assert(mt6762_adc_sample(&io,3,&mv)==-3 && mv==777 && a.reads==161);
    a=(struct adc){.out=0x8000,.address=0x108e,.pending=1};
    assert(mt6762_adc_sample(&io,3,&mv)==-4 && mv==777);
    a=(struct adc){.out=0x8fff,.address=0x108e,.pending=1};
    assert(mt6762_adc_sample(&io,3,&mv)==-4 && mv==777);
    a=(struct adc){.address=0x108e,.we=-9};
    assert(mt6762_adc_sample(&io,3,&mv)==-2 && !a.reads && mv==777);
    a=(struct adc){.address=0x108e,.re=-8};
    assert(mt6762_adc_sample(&io,3,&mv)==-2 && mv==777);
    a=(struct adc){.out=0x8000|1400,.address=0x108e};
    assert(mt6762_adc_sample(&io,3,&mv)==-5 && mv==777);
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
int main(void) {wacs_tests();entry_tests();adc_tests();keys_tests();puts("native PWRAP profiles/admission, ADC and button tests: PASS");return 0;}
