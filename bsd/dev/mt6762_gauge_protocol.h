/* MT6357 snapshot protocol. The only writes are owned latch handshakes;
 * never reset time, charge, offset, gain, or the analog gauge. */
#ifndef MT6762_GAUGE_PROTOCOL_H
#define MT6762_GAUGE_PROTOCOL_H
#include <stdint.h>
struct mt6762_gauge_io {
    void *context;
    int (*read)(void *,uint16_t,uint16_t *);
    int (*write)(void *,uint16_t,uint16_t);
    void (*delay_us)(void *,unsigned);
};
struct mt6762_gauge_snapshot {uint16_t current,car_low,car_high;uint64_t ticks;};
struct mt6762_gauge_transport {struct mt6762_gauge_io io;unsigned fault;};
static inline int mt6762_gauge_poll(struct mt6762_gauge_transport *t,unsigned ready,uint16_t *v)
{
    for(unsigned i=0;i<1000;i++) {
        if(t->io.read(t->io.context,0xd0a,v))return -1;
        if(!!(*v&0x8000)==ready)return 0;
        t->io.delay_us(t->io.context,10);
    }
    return -3;
}
static inline int mt6762_gauge_capture(struct mt6762_gauge_transport *t,struct mt6762_gauge_snapshot *out)
{
    struct mt6762_gauge_snapshot sample;
    uint16_t original,control,clock,on,lo,hi,top;
    if(!t || !out || !t->io.read || !t->io.write || !t->io.delay_us || t->fault)return -1;
    if(t->io.read(t->io.context,0xc0c,&clock) || t->io.read(t->io.context,0xd08,&on) ||
       t->io.read(t->io.context,0xd0a,&original))goto fault;
    /* Digital/analog clock gates, FG_ON, and all commands idle. Never consume
     * another reader's latch or carry a reset bit into an RMW. */
    if((clock&0x18) || !(on&1) || (original&0x9f0f))goto fault;
    if(t->io.write(t->io.context,0xd0a,original|1) || mt6762_gauge_poll(t,1,&control))goto fault;
    if((control&0x7fff)!=(original|1))goto fault;
    if(t->io.read(t->io.context,0xd8a,&sample.current) ||
       t->io.read(t->io.context,0xd12,&sample.car_low) ||
       t->io.read(t->io.context,0xd14,&sample.car_high) ||
       t->io.read(t->io.context,0xd20,&lo) ||
       t->io.read(t->io.context,0xd22,&hi) ||
       t->io.read(t->io.context,0xd24,&top))goto fault;
    if(top&~1u)goto fault;
    sample.ticks=((uint64_t)top<<32)|((uint64_t)hi<<16)|lo;
    /* Exact modern-stock release order: CLEAR=1, READ_PRE=0, wait, CLEAR=0. */
    if(t->io.write(t->io.context,0xd0a,original|9) ||
       t->io.write(t->io.context,0xd0a,original|8) ||
       mt6762_gauge_poll(t,0,&control))goto fault;
    if((control&0x7fff)!=(original|8) || t->io.write(t->io.context,0xd0a,original) ||
       t->io.read(t->io.context,0xd0a,&control) || control!=original)goto fault;
    *out=sample;return 0;
fault:
    /* Outcome/ownership is uncertain after a failed handshake. No speculative
     * clear/reset or new request is permitted until a new boot handoff. */
    t->fault=1;return -2;
}
static inline int mt6762_gauge_current(uint16_t raw,unsigned rfg,unsigned tune,int *ua)
{
    int negative=!!(raw&0x8000);
    int64_t value=negative?(raw^0xffff):raw;
    if(!ua || !rfg || rfg>10000 || !tune || tune>10000)return -1;
    value=value*314331/100000; /* Stock0.1mA quantization before calibration. */
    value=value*100/rfg;
    value=value*tune/1000;
    value*=100;
    if(value>2147483647)return -1;
    *ua=(int)(negative?-value:value);return 0;
}
static inline int mt6762_gauge_charge(uint16_t low,uint16_t high,unsigned rfg,unsigned tune,int64_t *uah)
{
    unsigned count=(low>>11)|((unsigned)(high&0x7fff)<<5),negative=high>>15;
    int64_t value=count;
    if(!uah || !rfg || rfg>10000 || !tune || tune>10000)return -1;
    if(count==0 || count==0xfffff)value=0;
    else if(negative)value=0xfffff-count;
    value=((value*11176/1000)/10+5)/10; /* Stock0.1mAh rounding. */
    value=value*100/rfg;
    value=value*tune/1000;
    *uah=(negative?-value:value)*100;return 0;
}
static inline int mt6762_gauge_progress(uint64_t before,uint64_t after)
{
    const uint64_t mask=(1ull<<33)-1;
    if((before|after)&~mask)return 0;
    uint64_t delta=(after-before)&mask;
    return delta && delta<(1ull<<32);
}
#endif
