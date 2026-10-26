/* SPDX-License-Identifier: MIT */
#define main existing_protocol_tests
#include "test_msdc_pio.c"
#undef main
#include "mt6762_msdc_admission.h"

struct gate_fixture {
    /* Existing protocol fixture callbacks accept this first member. */
    struct fixture hw;
    struct mt6762_msdc_admission gate;
    unsigned before,full,after,pmic_reads,before_cost,full_cost,after_cost;
    unsigned fail_before,fail_full,fail_after;
};
static int gate_before(void *ctx)
{
    struct gate_fixture *f=ctx;
    f->before++;f->hw.time+=f->before_cost;
    return f->fail_before==f->before;
}
static int gate_full(void *ctx)
{
    struct gate_fixture *f=ctx;
    f->full++;f->pmic_reads+=10;f->hw.time+=f->full_cost;
    return f->fail_full==f->full;
}
static int gate_after(void *ctx)
{
    struct gate_fixture *f=ctx;
    f->after++;f->hw.time+=f->after_cost;
    return f->fail_after==f->after;
}
static int gate_admit(void *ctx)
{
    struct gate_fixture *f=ctx;
    const struct mt6762_msdc_admission_io io={ctx,time_us,gate_before,gate_full,gate_after};
    return mt6762_msdc_admission_check(&f->gate,&io);
}
static void gate_setup(struct gate_fixture *f)
{
    memset(f,0,sizeof(*f));setup(&f->hw);
    f->before_cost=5;f->full_cost=50;f->after_cost=5;
}
static void protocol_setup(struct gate_fixture *f,struct mt6762_msdc *s)
{
    gate_setup(f);memset(s,0,sizeof(*s));
    const struct mt6762_msdc_io io={f,gate_admit,read32,write32,time_us,delay_us};
    const struct mt6762_msdc_config cfg={8,1,0x89,0x20000,100,200000000};
    assert(!mt6762_msdc_init(s,&io,&cfg));
    memset(&f->gate,0,sizeof(f->gate));
    f->before=f->full=f->after=f->pmic_reads=0;
}
int main(void)
{
    struct gate_fixture f;struct mt6762_msdc s;uint8_t out[512];
    existing_protocol_tests();
    protocol_setup(&f,&s);
    unsigned commands=f.hw.commands;
    assert(!mt6762_msdc_read512(&s,0,out));
    assert(!memcmp(out,f.hw.sector,512));
    assert(f.gate.calls==7 && f.gate.full==1 && f.gate.reused==6);
    assert(f.before==7 && f.after==7 && f.pmic_reads==10);
    assert(f.gate.full_us==60 && f.gate.full_max_us==60);
    assert(f.hw.commands-commands==3); /* same CMD13/CMD17/CMD13 */

    /* Scheduling before the reuse decision expires the old observation. */
    f.before_cost=1000;
    assert(!gate_admit(&f));
    assert(f.gate.full==2 && f.gate.slow_full==1 && !f.gate.valid);
    f.before_cost=5;
    assert(!gate_admit(&f) && f.gate.full==3 && f.gate.valid);

    /* Age is from observation BEGINNING; exact expiry cannot be extended by
     * stamping completion. Slow observations grant no reusable window. */
    gate_setup(&f);assert(!gate_admit(&f));
    f.hw.time=999;f.before_cost=f.after_cost=0;
    assert(!gate_admit(&f) && f.gate.reused==1);
    f.hw.time=1000;assert(!gate_admit(&f) && f.gate.full==2);
    gate_setup(&f);f.full_cost=1000;
    for(unsigned i=0;i<7;i++)assert(!gate_admit(&f));
    assert(f.gate.full==7 && f.gate.slow_full==7 && !f.gate.reused && f.pmic_reads==70);

    /* Even a stopped timer cannot permit unlimited completed sectors. */
    gate_setup(&f);f.before_cost=f.full_cost=f.after_cost=0;
    for(unsigned sector=0;sector<256;sector++) {
        for(unsigned phase=0;phase<7;phase++)assert(!gate_admit(&f));
        mt6762_msdc_admission_sector_done(&f.gate);
    }
    assert(f.gate.full==1 && f.gate.reused==1791 && !f.gate.valid);
    assert(!gate_admit(&f) && f.gate.full==2);

    /* A backward timer is terminal for this admission, even inside a window. */
    gate_setup(&f);assert(!gate_admit(&f));f.hw.time--;
    assert(gate_admit(&f)<0 && f.gate.clock_reversals==1 && !f.gate.valid);

    /* Cheap checks still run in every phase. Each failure rejects the staged
     * sector, faults the protocol and prevents subsequent MMIO/commands. */
    for(unsigned phase=1;phase<=7;phase++) {
        protocol_setup(&f,&s);f.fail_before=phase;memset(out,0xa5,512);
        assert(mt6762_msdc_read512(&s,0,out)==MT6762_MSDC_OWNERSHIP);
        assert(s.faulted && !f.gate.valid && f.gate.failures==1);
        for(unsigned i=0;i<512;i++)assert(out[i]==0xa5);
        unsigned rd=f.hw.reads,wr=f.hw.writes;
        assert(mt6762_msdc_read512(&s,0,out)==MT6762_MSDC_FAULTED);
        assert(rd==f.hw.reads && wr==f.hw.writes);
        protocol_setup(&f,&s);f.fail_after=phase;memset(out,0xa5,512);
        assert(mt6762_msdc_read512(&s,0,out)==MT6762_MSDC_OWNERSHIP);
        assert(s.faulted && !f.gate.valid && f.gate.failures==1);
        for(unsigned i=0;i<512;i++)assert(out[i]==0xa5);
    }
    /* Expired static state is not served on refresh failure. */
    protocol_setup(&f,&s);assert(!mt6762_msdc_read512(&s,0,out));
    f.hw.time+=1000;f.fail_full=f.full+1;memset(out,0xa5,512);
    unsigned wr=f.hw.writes;
    assert(mt6762_msdc_read512(&s,0,out)==MT6762_MSDC_OWNERSHIP);
    assert(f.hw.writes==wr && s.faulted && !f.gate.valid);
    for(unsigned i=0;i<512;i++)assert(out[i]==0xa5);
    puts("PASS: real PIO engine keeps seven dynamic admissions/three commands; bounded static reuse, slow/expired/reversed time and phase faults");
    return 0;
}
