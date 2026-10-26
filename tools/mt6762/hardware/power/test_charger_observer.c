#include <assert.h>
#include <stdio.h>
#include "mt6762_charger_observer.h"
static int read_reg(struct mt6762_charger_observer *s,uint64_t us,uint8_t reg)
{return mt6762_charger_observer_request(s,us,0x6a,&reg,1,1);}
int main(void)
{
    struct mt6762_charger_observer s={0};
    for(unsigned cycle=0;cycle<100;cycle++) {
        uint64_t t=(uint64_t)cycle*1000000;
        assert(read_reg(&s,t,3));assert(mt6762_charger_observer_complete(&s,t+10,0));
        assert(read_reg(&s,t+100,1));assert(mt6762_charger_observer_complete(&s,t+110,0));
        assert(read_reg(&s,t+200,0));assert(mt6762_charger_observer_complete(&s,t+210,0));
        assert(s.index==0 && !s.faulted);
        assert(!read_reg(&s,t+499999,3));
    }
    /* Denied shapes and targets must not consume an attempt or change state. */
    for(unsigned a=0;a<128;a++)for(unsigned reg=0;reg<256;reg++) {
        struct mt6762_charger_observer q={0};uint8_t r=reg;
        int ok=mt6762_charger_observer_request(&q,100, a,&r,1,1);
        assert(ok==(a==0x6a && reg==3));
        if(!ok)assert(!q.started && !q.index && !q.faulted);
    }
    for(unsigned nt=0;nt<5;nt++)for(unsigned nr=0;nr<5;nr++) {
        struct mt6762_charger_observer q={0};uint8_t r=3;
        assert(mt6762_charger_observer_request(&q,100,0x6a,&r,nt,nr)==(nt==1&&nr==1));
    }
    s=(struct mt6762_charger_observer){0};
    assert(read_reg(&s,1000000,3));assert(!read_reg(&s,1100001,1));assert(s.faulted);
    assert(!read_reg(&s,2000000,3));
    s=(struct mt6762_charger_observer){0};
    assert(read_reg(&s,1000000,3));assert(!read_reg(&s,999999,1));assert(s.faulted);
    s=(struct mt6762_charger_observer){0};
    assert(read_reg(&s,1000000,3));s.faulted=1;assert(!read_reg(&s,1000100,1));
    s=(struct mt6762_charger_observer){0};
    assert(read_reg(&s,1000000,3));assert(!mt6762_charger_observer_complete(&s,1100001,0));
    assert(s.faulted);
    s=(struct mt6762_charger_observer){0};
    assert(read_reg(&s,1000000,3));assert(!mt6762_charger_observer_complete(&s,1000001,-1));
    assert(s.faulted);
    puts("PSC observer: repeated samples, exact targets/shapes, rate/lease, clock reversal and terminal fault PASS");
}
