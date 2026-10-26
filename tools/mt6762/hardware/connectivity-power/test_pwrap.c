/* SPDX-License-Identifier: MIT -- executes the unchanged native WACS engine. */
#include <assert.h>
#include <stdio.h>
#include "pwrap_readonly.h"
struct mock {unsigned held,locks,unlocks,admissions,reads,writes,delay,phase;int acquire_error,admit_error,fail_phase;uint16_t reg;};
static int acquire(void *v){struct mock *m=v;m->locks++;assert(!m->held);if(m->acquire_error)return m->acquire_error;m->held=1;return 0;}
static void release(void *v){struct mock *m=v;assert(m->held);m->held=0;m->unlocks++;}
static int admit(void *v){struct mock *m=v;assert(m->held);m->admissions++;return m->admit_error;}
static uint32_t rd(void *v,uint32_t off)
{
    struct mock *m=v;assert(m->held && off==0xc24);m->reads++;
    if((int)m->phase==m->fail_phase)return (1u<<22)|(2u<<16);
    return (1u<<22)|(m->phase==1?((6u<<16)|0x4321):0);
}
static void wr(void *v,uint32_t off,uint32_t value)
{
    struct mock *m=v;assert(m->held);m->writes++;
    if(m->phase==0) {
        assert(off==0xc20 && !(value&0x80000000u));
        assert(value==((uint32_t)(m->reg>>1)<<16));m->phase=1;
    } else {assert(m->phase==1 && off==0xc28 && value==1);m->phase=2;}
}
static void delay(void *v,unsigned us){struct mock *m=v;assert(m->held && us==10);m->delay+=us;}
int main(void)
{
    struct mock m={.fail_phase=-1};struct mt6762_wacs_io io={&m,rd,wr,delay};
    struct mt6762_connectivity_pwrap p={&m,&io,acquire,release,admit,0};uint16_t value;
    for(unsigned i=0;i<19;i++) {
        m=(struct mock){.fail_phase=-1,.reg=mt6762_connectivity_pmic_regs[i]};value=0xeeee;p.fault=0;
        assert(!mt6762_connectivity_pwrap_read(&p,m.reg,&value));
        assert(value==0x4321 && m.locks==1 && m.unlocks==1 && m.admissions==1 && m.reads==3 && m.writes==2);
    }
    const uint16_t forbidden[]={0,6,0x1a5c,0x1a5e,0x1b8c,0x1b8e,0x1b92,0x1b94,0x110e,0xffff};
    for(unsigned i=0;i<sizeof(forbidden)/sizeof(*forbidden);i++) {
        m=(struct mock){0};assert(mt6762_connectivity_pwrap_read(&p,forbidden[i],&value)==-1001);
        assert(!m.locks && !m.reads && !m.writes);
    }
    for(int phase=0;phase<3;phase++) {
        m=(struct mock){.fail_phase=phase,.reg=0x1a58};p.fault=0;value=0xeeee;
        assert(mt6762_connectivity_pwrap_read(&p,m.reg,&value)==-3);
        assert(p.fault && !m.held && m.unlocks==1 && m.writes==(unsigned)phase && value==0xeeee);
        assert(m.delay==10000 && m.reads==1000u+(unsigned)phase);
        unsigned reads=m.reads,writes=m.writes,admits=m.admissions;
        assert(mt6762_connectivity_pwrap_read(&p,m.reg,&value)==-1002);
        assert(m.reads==reads && m.writes==writes && m.admissions==admits && !m.held);
    }
    m=(struct mock){.admit_error=-88,.reg=0x1a58};p.fault=0;
    assert(mt6762_connectivity_pwrap_read(&p,m.reg,&value)==-88 && p.fault && m.unlocks==1 && !m.reads && !m.writes);
    m=(struct mock){.acquire_error=-99,.reg=0x1a58};p.fault=0;
    assert(mt6762_connectivity_pwrap_read(&p,m.reg,&value)==-99 && !p.fault && !m.unlocks && !m.admissions && !m.reads);
    p.acquire=NULL;assert(mt6762_connectivity_pwrap_read(&p,0x1a58,&value)==-1001);
    puts("connectivity WACS: exact19 read commands, lock/admission, no PMIC write bit, timeout phases, fault latch PASS");
    return 0;
}
