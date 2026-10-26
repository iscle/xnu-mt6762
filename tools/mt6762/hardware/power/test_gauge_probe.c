/* Portable finite capability tests; no device or kernel execution. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "mt6762_gauge_probe.h"
static struct mt6762_gauge_probe_budget armed(unsigned phase)
{
    struct mt6762_gauge_probe_budget b={0};
    static const uint16_t values[]={1,9,8,0};
    assert(mt6762_gauge_probe_begin(&b,0));
    assert(mt6762_gauge_probe_arm(&b));
    for(unsigned i=0;i<phase;i++) {
        assert(mt6762_gauge_probe_write_begin(&b,0xd0a,values[i]));
        assert(mt6762_gauge_probe_write_end(&b,0));
    }
    return b;
}
int main(void)
{
    struct mt6762_gauge_probe_profile p={1,100,1000,{0x129,0x416,1,0,0x416}},q;
    assert(mt6762_gauge_probe_profile_ok(&p) && !mt6762_gauge_probe_profile_ok(NULL));
    for(unsigned i=0;i<8;i++) {
        uint32_t words[8];assert(sizeof(words)==sizeof(q));
        memcpy(words,&p,sizeof(words));words[i]^=1;memcpy(&q,words,sizeof(q));
        assert(!mt6762_gauge_probe_profile_ok(&q));
    }
    uint64_t deadline=42;
    assert(!mt6762_gauge_probe_deadline(UINT64_MAX-1,2,&deadline) && deadline==42);
    assert(!mt6762_gauge_probe_deadline(1,0,&deadline));
    assert(!mt6762_gauge_probe_deadline(1,1,NULL));
    assert(mt6762_gauge_probe_deadline(10,20,&deadline) && deadline==30);
    assert(!mt6762_gauge_probe_in_lease(10,30,9));
    assert(mt6762_gauge_probe_in_lease(10,30,10));
    assert(mt6762_gauge_probe_in_lease(10,30,29));
    assert(!mt6762_gauge_probe_in_lease(10,30,30));
    assert(!mt6762_gauge_probe_in_lease(10,10,10));
    static const uint16_t sequence[]={1,9,8,0};
    for(unsigned phase=0;phase<4;phase++)for(unsigned value=0;value<65536;value++) {
        struct mt6762_gauge_probe_budget b=armed(phase);
        int ok=mt6762_gauge_probe_write_begin(&b,0xd0a,(uint16_t)value);
        assert(ok==(value==sequence[phase]));
        assert(b.attempted==phase+(unsigned)ok);
        if(!ok)assert(b.fault && !mt6762_gauge_probe_write_begin(&b,0xd0a,sequence[phase]));
    }
    for(unsigned reg=0;reg<65536;reg++) {
        struct mt6762_gauge_probe_budget b=armed(0);
        assert(mt6762_gauge_probe_write_begin(&b,(uint16_t)reg,1)==(reg==0xd0a));
    }
    for(unsigned phase=0;phase<4;phase++) {
        struct mt6762_gauge_probe_budget b=armed(phase);
        assert(mt6762_gauge_probe_write_begin(&b,0xd0a,sequence[phase]));
        assert(!mt6762_gauge_probe_read_allowed(&b,0xd0a));
        assert(!mt6762_gauge_probe_write_end(&b,-1));
        assert(b.fault && !b.pending && b.attempted==phase+1 && b.completed==phase);
        assert(!mt6762_gauge_probe_write_begin(&b,0xd0a,sequence[phase]));
        assert(!mt6762_gauge_probe_begin(&b,0));
    }
    struct mt6762_gauge_probe_budget b={0};
    assert(!mt6762_gauge_probe_read_allowed(&b,8));
    assert(mt6762_gauge_probe_begin(&b,0));
    assert(mt6762_gauge_probe_read_allowed(&b,8));
    assert(!mt6762_gauge_probe_read_allowed(&b,0xd8a));
    assert(!mt6762_gauge_probe_write_begin(&b,0xd0a,1)); /* Not armed. */
    b=armed(0);assert(!mt6762_gauge_probe_read_allowed(&b,0xd8a));
    b=armed(1);assert(mt6762_gauge_probe_read_allowed(&b,0xd8a));
    b=armed(2);assert(!mt6762_gauge_probe_read_allowed(&b,0xd8a));
    b=armed(0);assert(!mt6762_gauge_probe_finish(&b));
    b=armed(4);assert(mt6762_gauge_probe_finish(&b));
    assert(!mt6762_gauge_probe_read_allowed(&b,8));
    assert(mt6762_gauge_probe_begin(&b,1) && mt6762_gauge_probe_arm(&b));
    for(unsigned i=0;i<4;i++) {
        assert(mt6762_gauge_probe_write_begin(&b,0xd0a,sequence[i]));
        assert(mt6762_gauge_probe_write_end(&b,0));
    }
    assert(mt6762_gauge_probe_finish(&b) && b.completed==8 && b.attempted==8);
    assert(!mt6762_gauge_probe_begin(&b,2));
    assert(!mt6762_gauge_probe_write_begin(&b,0xd0a,1));
    b=armed(0);b.attempted=8;assert(!mt6762_gauge_probe_write_begin(&b,0xd0a,1));
    b=armed(0);b.pending=1;assert(!mt6762_gauge_probe_write_begin(&b,0xd0a,1));
    b=armed(0);assert(!mt6762_gauge_probe_arm(&b));
    b=armed(0);assert(!mt6762_gauge_probe_begin(&b,0));
    b=armed(0);assert(!mt6762_gauge_probe_write_end(&b,0));
    assert(!mt6762_gauge_probe_write_begin(NULL,0xd0a,1));
    puts("gauge finite policy: exact profile, exhaustive address/value rejection, phase/budget/sticky failure, leases PASS");
}
