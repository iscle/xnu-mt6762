/* SPDX-License-Identifier: MIT -- execute the actual digital power core. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "conn_power.h"

enum { RGU=0x10007018,SPM=0x1000632c,ACK0=0x10006180,ACK1=0x10006184,
       EN=0x10001220,STA=0x10001228,EN1=0x10001250,STA1=0x10001258,
       CLR=0x100012a4,CLR1=0x100012ac,ID=0x180b1010 };
struct mock {
    struct mt6762_conn_report *r;
    uint32_t rgu,spm,en,sta,en1,sta1,rgu_other,spm_other;
    uint64_t now,step;
    unsigned ops,reads,writes,admissions,barriers,relaxes,times;
    unsigned write_sequence,ack0_polls,ack1_polls,prot_polls,prot1_polls,id_reads;
    int fail_op,fail_admission,failed,apply_failed_write;
    int no_ack0,no_ack1,initial_ack0,initial_ack1,stuck_protect,wrong_id_reads;
    int corrupt_id_guard,corrupted,drift_spm,drift_done,skip_reset;
    int slow_op;
};
static uint64_t ticks(void *v)
{struct mock *m=v;uint64_t result=m->now;m->now+=m->step;m->times++;return result;}
static void barrier(void *v){((struct mock *)v)->barriers++;}
static void relax(void *v){((struct mock *)v)->relaxes++;}
static int prerequisites(void *v,enum mt6762_conn_stage stage)
{
    struct mock *m=v;assert(!m->failed);m->admissions++;
    if((int)m->admissions==m->fail_admission) {m->failed=1;return -42;}
    if(stage==MT6762_CONN_READ_ID && !m->corrupted && m->corrupt_id_guard) {
        m->corrupted=1;
        switch(m->corrupt_id_guard) {
        case 1:m->rgu&=~0x1000u;break;case 2:m->spm^=1;break;
        case 3:m->no_ack0=1;break;case 4:m->no_ack1=1;break;
        case 5:m->en|=0x2000;break;case 6:m->sta|=0x2000;break;
        case 7:m->en1|=0x40000;break;case 8:m->sta1|=0x40000;break;
        }
    }
    if(stage==MT6762_CONN_ENABLE_CLOCK && m->drift_spm && !m->drift_done) {
        m->spm^=1;m->drift_done=1;
    }
    return 0;
}
static int op(struct mock *m)
{
    assert(!m->failed);m->ops++;
    if((int)m->ops==m->slow_op)m->now+=UINT64_C(13000000);
    if((int)m->ops==m->fail_op) {m->failed=1;return -77;}
    return 0;
}
static int rd(void *v,uint32_t address,uint32_t *value)
{
    struct mock *m=v;m->reads++;
    if(op(m)) {*value=0xdeadbeef;return -77;}
    assert(address!=CLR && address!=CLR1); /* never read command aliases */
    switch(address) {
    case RGU:*value=m->rgu;break;
    case SPM:*value=m->spm;break;
    case ACK0:
        *value=0x434c|(m->initial_ack0?2:0);
        if(m->write_sequence>=3 && !m->no_ack0 && ++m->ack0_polls>=2)*value|=2;
        break;
    case ACK1:
        *value=0x434c|(m->initial_ack1?2:0);
        if(m->write_sequence>=3 && !m->no_ack1 && ++m->ack1_polls>=4)*value|=2;
        break;
    case EN:*value=m->en;break;
    case STA:
        if(m->r->stage!=MT6762_CONN_READ_ID && m->write_sequence>=7 &&
           !(m->stuck_protect==1 && m->write_sequence==7) &&
           !(m->stuck_protect==2 && m->write_sequence==8) &&
           ++m->prot_polls>=3)m->sta=m->en;
        *value=m->sta;break;
    case EN1:*value=m->en1;break;
    case STA1:
        if(m->r->stage!=MT6762_CONN_READ_ID && m->write_sequence>=9 &&
           m->stuck_protect!=3 && ++m->prot1_polls>=3)m->sta1=m->en1;
        *value=m->sta1;break;
    case ID:
        assert(m->rgu&0x1000);assert((m->spm&0x1f)==0x0d);
        assert(!m->no_ack0 && !m->no_ack1 && m->ack0_polls>=2 && m->ack1_polls>=4);
        assert(!(m->en&0x16000) && !(m->sta&0x16000));
        assert(!(m->en1&0x40000) && !(m->sta1&0x40000));
        assert(m->write_sequence==9 && m->r->stage==MT6762_CONN_READ_ID);
        *value=(int)m->id_reads++ < m->wrong_id_reads?0:0x10020300;
        break;
    default:assert(!"read outside exact whitelist");
    }
    return 0;
}
static int wr(void *v,uint32_t address,uint32_t value)
{
    struct mock *m=v;m->writes++;
    int error=op(m);
    if(error && !m->apply_failed_write)return error;
    assert(m->write_sequence<9);
    if(m->write_sequence==0) {
        assert(address==RGU && value==(m->rgu_other|0x88001000));
        if(!m->skip_reset)m->rgu=value&0x00ffffff; /* key is not stored */
    } else if(m->write_sequence<6) {
        static const unsigned expected[]={0,0x16,0x1e,0x0e,0x0c,0x0d};
        assert(m->rgu&0x1000);
        assert(address==SPM && value==(m->spm_other|expected[m->write_sequence]));
        if(m->write_sequence>=3)assert(m->ack0_polls>=2 && m->ack1_polls>=4);
        m->spm=value;
    } else if(m->write_sequence==6) {
        assert(address==CLR && value==0x14000 && (m->spm&0x1f)==0x0d);
        m->en&=~value;m->prot_polls=0;
    } else if(m->write_sequence==7) {
        assert(address==CLR && value==0x2000 && (m->sta&0x16000)==0x2000);
        m->en&=~value;m->prot_polls=0;
    } else {
        assert(address==CLR1 && value==0x40000 && !(m->sta&0x16000));
        m->en1&=~value;m->prot1_polls=0;
    }
    m->write_sequence++;
    return error;
}
static struct mt6762_conn_io setup(struct mock *m,struct mt6762_conn_report *r)
{
    *m=(struct mock){.r=r,.step=13,.rgu_other=0x00400255,.spm_other=0x54100000,
        .fail_op=-1,.fail_admission=-1,.slow_op=-1};
    m->rgu=m->rgu_other;m->spm=m->spm_other|0x12;
    m->en=m->sta=0x80016000;m->en1=m->sta1=0x90040000;
    memset(r,0xa5,sizeof(*r));
    return (struct mt6762_conn_io){m,rd,wr,ticks,barrier,relax,prerequisites,
        13000000,100000,1000000,100000};
}
int main(void)
{
    struct mock m;struct mt6762_conn_report r;struct mt6762_conn_io io=setup(&m,&r);
    assert(mt6762_conn_power_reset_held(&io,&r,0)==MT6762_CONN_DISABLED);
    assert(!m.ops && !m.times && !m.admissions && !m.barriers && !m.relaxes);
    assert(mt6762_conn_power_reset_held(NULL,&r,0)==MT6762_CONN_DISABLED);
    for(unsigned bad=0;bad<16;bad++) {
        io=setup(&m,&r);int enabled=1;
        switch(bad) {
        case 0:io.read32=NULL;break;case 1:io.write32=NULL;break;
        case 2:io.ticks=NULL;break;case 3:io.barrier=NULL;break;
        case 4:io.relax=NULL;break;case 5:io.prerequisites=NULL;break;
        case 6:io.counter_hz=0;break;case 7:io.transition_timeout_us=0;break;
        case 8:io.transition_timeout_us=100001;break;case 9:io.total_timeout_us=0;break;
        case 10:io.total_timeout_us=1000001;break;case 11:io.iteration_limit=0;break;
        case 12:io.iteration_limit=10000001;break;case 13:enabled=-1;break;
        case 14:enabled=2;break;case 15:io.counter_hz=26000000;break;
        }
        assert(mt6762_conn_power_reset_held(&io,&r,enabled)==MT6762_CONN_ARGUMENT);
        assert(!m.ops && !m.times && !m.admissions);
    }
    io=setup(&m,&r);
    assert(!mt6762_conn_power_reset_held(&io,&r,1));
    assert(r.stage==MT6762_CONN_RESET_HELD_ID_VERIFIED && r.reset_observed && r.id_valid && r.id==0x10020300);
    assert(m.write_sequence==9 && r.write_attempts==9 && r.writes==9 && m.id_reads==1);
    assert(m.en==0x80000000 && m.sta==0x80000000 && m.en1==0x90000000 && m.sta1==0x90000000);
    assert(r.snapshot_valid==0xff && r.callback_error==0);
    unsigned operations=m.ops,admissions=m.admissions;
    /* Every actual MMIO and prerequisite callback can fail. No subsequent
     * operation is permitted; the model would assert on rollback/retry. */
    for(unsigned n=1;n<=operations;n++) {
        io=setup(&m,&r);m.fail_op=(int)n;
        assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_IO);
        assert(m.ops==n && r.callback_error==-77 && !m.id_reads);
        if(!r.last_access_write)assert(!r.last_value_valid);
        if(m.write_sequence)assert(m.rgu&0x1000);
    }
    for(unsigned n=1;n<=admissions;n++) {
        io=setup(&m,&r);m.fail_admission=(int)n;
        assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_PREREQUISITE);
        assert(m.admissions==n && r.callback_error==-42);
        if(m.write_sequence)assert(m.rgu&0x1000);
    }
    /* Failed writes may have reached hardware: retain it, do not force off. */
    io=setup(&m,&r);m.fail_op=18;m.apply_failed_write=1;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_IO);
    assert(m.write_sequence==1 && (m.rgu&0x1000) && r.reset_write_attempted && !r.power_write_attempted);
    /* Reject each cold-entry mask mismatch before the first write. */
    for(unsigned n=0;n<16;n++) {
        io=setup(&m,&r);
        if(n<5)m.spm^=1u<<n;
        else if(n<8)m.en^=1u<<(n==5?13:n==6?14:16);
        else if(n<11)m.sta^=1u<<(n==8?13:n==9?14:16);
        else if(n==11)m.en1^=1u<<18;
        else if(n==12)m.sta1^=1u<<18;
        else if(n==13)m.rgu|=0x10000000;
        else if(n==14)m.initial_ack0=1;
        else m.initial_ack1=1;
        assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_NOT_COLD && !m.writes);
    }
    /* A controller that ignores RESET assertion never receives power writes. */
    io=setup(&m,&r);m.skip_reset=1;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_STATE_CHANGED && m.write_sequence==1);
    for(unsigned n=0;n<2;n++) {
        io=setup(&m,&r);io.iteration_limit=8;m.no_ack0=n==0;m.no_ack1=n==1;
        assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_ITERATION_LIMIT);
        assert(r.stage==MT6762_CONN_POWER_ACK && m.write_sequence==3 && !m.id_reads);
    }
    for(unsigned n=1;n<=3;n++) {
        io=setup(&m,&r);io.iteration_limit=8;m.stuck_protect=(int)n;
        assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_ITERATION_LIMIT);
        assert(r.stage==MT6762_CONN_RELEASE_PROTECT_14_16+n-1 && m.write_sequence==6+n && !m.id_reads);
    }
    io=setup(&m,&r);m.drift_spm=1;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_STATE_CHANGED && m.write_sequence==3);
    for(unsigned n=1;n<=8;n++) {
        io=setup(&m,&r);m.corrupt_id_guard=(int)n;
        assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_STATE_CHANGED);
        assert(m.write_sequence==9 && !m.id_reads);
    }
    io=setup(&m,&r);m.step=0;io.iteration_limit=8;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_ITERATION_LIMIT);
    assert(r.stage==MT6762_CONN_SETTLE && !m.id_reads);
    io=setup(&m,&r);m.now=UINT64_MAX-1000;
    assert(!mt6762_conn_power_reset_held(&io,&r,1) && r.ended_ticks<r.began_ticks);
    /* A slow successful read is retained but cannot permit the next write. */
    io=setup(&m,&r);m.slow_op=19;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_TIMEOUT && m.write_sequence==1);
    io=setup(&m,&r);m.step=13000000;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_TIMEOUT && !m.ops);
    io=setup(&m,&r);m.no_ack1=1;io.transition_timeout_us=3000;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_TIMEOUT);
    assert(r.stage==MT6762_CONN_POWER_ACK && m.write_sequence==3);
    io=setup(&m,&r);m.wrong_id_reads=1;io.total_timeout_us=10000;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_TIMEOUT);
    assert(r.stage==MT6762_CONN_READ_ID && m.id_reads==1);
    io=setup(&m,&r);m.slow_op=(int)operations;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_TIMEOUT);
    assert(r.stage==MT6762_CONN_READ_ID && r.id_valid && r.id==0x10020300);
    io=setup(&m,&r);m.wrong_id_reads=2;
    assert(!mt6762_conn_power_reset_held(&io,&r,1) && m.id_reads==3 && m.write_sequence==9);
    assert(r.ended_ticks-r.began_ticks>=UINT64_C(40000)*13);
    io=setup(&m,&r);m.wrong_id_reads=20;
    assert(mt6762_conn_power_reset_held(&io,&r,1)==MT6762_CONN_ID_MISMATCH && m.id_reads==10);
    assert((m.rgu&0x1000) && (m.spm&0x1f)==0x0d && r.id_valid && r.id==0);
    /* Preserve unrelated control fields over many patterns. */
    uint32_t bits=0x12345678;
    for(unsigned n=0;n<64;n++) {
        io=setup(&m,&r);bits=bits*1664525u+1013904223u;
        m.rgu=m.rgu_other=bits&0x00ffefff;
        m.spm_other=bits&~0x1fu;m.spm=m.spm_other|0x12;
        assert(!mt6762_conn_power_reset_held(&io,&r,1));
    }
    printf("CONN core PASS: exact 9-write order, delayed dual ACK/protection, %u MMIO and %u admission fault sites, cold/state guards, retained-reset failures, bounded waits/wrap, delayed ID, unrelated fields\n",operations,admissions);
    return 0;
}
