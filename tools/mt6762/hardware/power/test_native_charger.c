#include <assert.h>
#include <stdio.h>
#include "../../../../bsd/dev/mt6762_charger_protocol.h"
struct model { uint8_t id,control; unsigned reads,writes; int fail_read,fail_write,no_latch,other_change; };
struct observation_model { uint8_t id,control,status; unsigned reads,writes; int fail; };
static int observation_read(void *p,uint8_t reg,uint8_t *v)
{
    static const uint8_t order[]={3,1,0};
    struct observation_model *m=p;
    assert(m->reads<3 && reg==order[m->reads]);
    if(++m->reads==(unsigned)m->fail)return -8;
    *v=reg==3?m->id:reg==1?m->control:m->status;
    return 0;
}
static int observation_write(void *p,uint8_t reg,uint8_t v)
{(void)reg;(void)v;((struct observation_model *)p)->writes++;return -9;}
static void observation_tests(void)
{
    struct observation_model m={0};
    struct mt6762_psc_io io={&m,observation_read,observation_write};
    struct mt6762_psc_observation out;
    for(unsigned control=0;control<256;control++)for(unsigned status=0;status<256;status++) {
        m=(struct observation_model){.id=0xf0,.control=control,.status=status};
        assert(!mt6762_psc_observe(&io,&out));
        assert(out.id==0xf0 && out.control==control && out.status==status);
        assert(m.reads==3 && !m.writes);
    }
    for(unsigned id=0;id<256;id++)if(id!=0xf0) {
        m=(struct observation_model){.id=id};out=(struct mt6762_psc_observation){0xaa,0xbb,0xcc};
        assert(mt6762_psc_observe(&io,&out)==-2 && m.reads==1 && !m.writes);
        assert(out.id==0xaa && out.control==0xbb && out.status==0xcc);
    }
    for(int failure=1;failure<=3;failure++) {
        m=(struct observation_model){.id=0xf0,.fail=failure};
        out=(struct mt6762_psc_observation){0xaa,0xbb,0xcc};
        assert(mt6762_psc_observe(&io,&out)==-8 && m.reads==(unsigned)failure && !m.writes);
        assert(out.id==0xaa && out.control==0xbb && out.status==0xcc);
    }
    m=(struct observation_model){.id=0xf0};io.write=NULL;
    assert(!mt6762_psc_observe(&io,&out) && m.reads==3);
    m.reads=0;
    assert(mt6762_psc_observe(NULL,&out)==-1 && mt6762_psc_observe(&io,NULL)==-1 && !m.reads);
    io.read=NULL;assert(mt6762_psc_observe(&io,&out)==-1 && !m.reads);
}
static int rd(void *p,uint8_t reg,uint8_t *v)
{
    struct model *m=p;m->reads++;
    if(m->fail_read==(int)m->reads)return -8;
    assert(reg==3 || reg==1);*v=reg==3?m->id:m->control;
    if(m->other_change && m->writes)*v^=0x40;
    return 0;
}
static int wr(void *p,uint8_t reg,uint8_t v)
{
    struct model *m=p;assert(reg==1);m->writes++;
    assert(v==(uint8_t)(m->control|4)); /* no other field changes */
    if(m->fail_write)return -9;
    if(!m->no_latch)m->control=v;
    return 0;
}
static void disable_tests(void)
{
    struct model m={.id=0xf0,.control=0xf8};
    struct mt6762_psc_io io={&m,rd,wr};uint8_t output=0xaa;
    assert(!mt6762_psc_disable_owned(&io,1,&output));
    assert(m.control==0xfc && output==0xfc && m.writes==1 && m.reads==3);
    m=(struct model){.id=0xf0,.control=0xfc};
    assert(!mt6762_psc_disable_owned(&io,1,&output) && !m.writes && m.reads==3);
    m=(struct model){.id=0xf0};output=0xaa;
    assert(mt6762_psc_disable_owned(&io,0,&output)==-1 && !m.reads && !m.writes);
    m=(struct model){.id=0xee};
    assert(mt6762_psc_disable_owned(&io,1,&output)==-2 && !m.writes && output==0xaa);
    m=(struct model){.id=0xf0,.control=1};
    assert(mt6762_psc_disable_owned(&io,1,&output)==-3 && !m.writes && output==0xaa);
    for(int n=1;n<=3;n++) {
        m=(struct model){.id=0xf0,.fail_read=n};
        assert(mt6762_psc_disable_owned(&io,1,&output)==-8 && output==0xaa);
        assert(m.writes==(unsigned)(n==3));
    }
    m=(struct model){.id=0xf0,.fail_write=1};
    assert(mt6762_psc_disable_owned(&io,1,&output)==-9 && output==0xaa);
    m=(struct model){.id=0xf0,.no_latch=1};
    assert(mt6762_psc_disable_owned(&io,1,&output)==-4 && output==0xaa);
    m=(struct model){.id=0xf0,.other_change=1};
    assert(mt6762_psc_disable_owned(&io,1,&output)==-4 && output==0xaa);
}
static void decoder_tests(void)
{
    uint32_t v=999;
    assert(!mt6762_psc_voltage_uv(0,0,&v) && v==4100000);
    assert(!mt6762_psc_voltage_uv(4,0,&v) && v==4100000);
    assert(!mt6762_psc_voltage_uv(8,0,&v) && v==4200000);
    assert(!mt6762_psc_voltage_uv(35*4,0,&v) && v==4200000);
    assert(!mt6762_psc_voltage_uv(36*4,0,&v) && v==4350000);
    assert(!mt6762_psc_voltage_uv(44*4,0x80,&v) && v==4370000);
    assert(!mt6762_psc_voltage_uv(45*4,0,&v) && v==4400000);
    assert(!mt6762_psc_voltage_uv(62*4,0x80,&v) && v==4420000);
    assert(mt6762_psc_voltage_uv(63*4,0,&v) && v==4420000);
    assert(!mt6762_psc_input_ua(0,&v) && v==150000);
    assert(!mt6762_psc_input_ua(0x40,&v) && v==500000);
    assert(!mt6762_psc_input_ua(0x80,&v) && v==800000);
    assert(mt6762_psc_input_ua(0xc0,&v) && v==800000);
    assert(!mt6762_psc_current_ua(0,0,50000,&v) && v==656000);
    assert(!mt6762_psc_current_ua(0x70,0,50000,&v) && v==1966000);
    assert(!mt6762_psc_current_ua(0x70,1,50000,&v) && v==1734000);
    assert(!mt6762_psc_current_ua(0x20,1,50000,&v) && v==800000);
    assert(!mt6762_psc_current_ua(0,0,56000,&v) && v==585714);
    assert(mt6762_psc_current_ua(0,0,0,&v) && v==585714);
    assert(mt6762_psc_current_ua(0x70,0,1,&v) && v==585714);
    assert(!mt6762_psc_termination_ua(0,50000,&v) && v==50000);
    assert(!mt6762_psc_termination_ua(7,50000,&v) && v==226000);
    assert(mt6762_psc_termination_ua(7,0,&v) && v==226000);
}
int main(void) {observation_tests();disable_tests();decoder_tests();puts("native charger observation, ownership, disable/readback, nominal datasheet decoders: PASS");return 0;}
