/* SPDX-License-Identifier: MIT -- finite capture33 gauge diagnostic policy.
 * No hardware callback, clock programming, general ownership or publication.
 * The unchanged native gauge protocol supplies the actual latch handshake. */
#ifndef MT6762_GAUGE_PROBE_H
#define MT6762_GAUGE_PROBE_H
#include <stdint.h>

struct mt6762_gauge_probe_profile {
    uint32_t version,rfg,tune,config[5];
};
static inline int mt6762_gauge_probe_profile_ok(const struct mt6762_gauge_probe_profile *p)
{
    static const uint32_t expected[5]={0x129,0x416,1,0,0x416};
    if(!p || p->version!=1 || p->rfg!=100 || p->tune!=1000)return 0;
    for(unsigned i=0;i<5;i++)if(p->config[i]!=expected[i])return 0;
    return 1;
}
static const uint16_t mt6762_gauge_probe_entry_regs[8]={
    8,0xc0c,0xd08,0xc8e,0xc90,0xd94,0xd96,0xd0a};
static const uint16_t mt6762_gauge_probe_entry_values[8]={
    0x5730,4,0x129,0x416,1,0,0x416,0};
struct mt6762_gauge_probe_budget {
    unsigned next_sample,active,armed,pending,attempted,completed,fault;
};
static inline int mt6762_gauge_probe_read_allowed(const struct mt6762_gauge_probe_budget *b,
    uint16_t reg)
{
    if(!b || b->fault || !b->active || b->pending || b->next_sample>=2 ||
       b->attempted!=b->completed)return 0;
    for(unsigned i=0;i<8;i++)if(reg==mt6762_gauge_probe_entry_regs[i])return 1;
    /* Data are observable only after this sample's READ_PRE write, before
     * its release sequence. A callback cannot read an inherited old latch. */
    return b->armed && b->completed==4*b->next_sample+1 &&
        (reg==0xd8a || reg==0xd12 || reg==0xd14 || reg==0xd20 || reg==0xd22 || reg==0xd24);
}
static inline int mt6762_gauge_probe_reject(struct mt6762_gauge_probe_budget *b)
{if(b)b->fault=1;return 0;}
static inline int mt6762_gauge_probe_begin(struct mt6762_gauge_probe_budget *b,unsigned sample)
{
    if(!b || b->fault || b->active || b->armed || b->pending || sample>=2 ||
       sample!=b->next_sample || b->attempted!=sample*4 || b->completed!=sample*4)
        return mt6762_gauge_probe_reject(b);
    b->active=1;return 1;
}
static inline int mt6762_gauge_probe_arm(struct mt6762_gauge_probe_budget *b)
{
    if(!b || b->fault || !b->active || b->armed || b->pending || b->next_sample>=2 ||
       b->attempted!=b->next_sample*4 || b->completed!=b->attempted)
        return mt6762_gauge_probe_reject(b);
    b->armed=1;return 1;
}
/* Admission consumes an attempted-write slot BEFORE the transport call. An
 * ambiguous/failed transaction can never be repeated through this budget. */
static inline int mt6762_gauge_probe_write_begin(struct mt6762_gauge_probe_budget *b,
    uint16_t reg,uint16_t value)
{
    static const uint16_t sequence[4]={1,9,8,0};
    if(!b || b->fault || !b->active || !b->armed || b->pending || b->next_sample>=2 ||
       b->attempted>=8 || b->attempted>=4*(b->next_sample+1) ||
       b->attempted!=b->completed || reg!=0xd0a || value!=sequence[b->attempted%4])
        return mt6762_gauge_probe_reject(b);
    b->pending=1;b->attempted++;return 1;
}
static inline int mt6762_gauge_probe_write_end(struct mt6762_gauge_probe_budget *b,int error)
{
    if(!b || b->fault || !b->pending || !b->active || !b->armed ||
       b->attempted!=b->completed+1 || b->attempted>8)
        return mt6762_gauge_probe_reject(b);
    b->pending=0;
    if(error)return mt6762_gauge_probe_reject(b);
    b->completed++;return 1;
}
static inline int mt6762_gauge_probe_finish(struct mt6762_gauge_probe_budget *b)
{
    if(!b || b->fault || !b->active || !b->armed || b->pending || b->next_sample>=2 ||
       b->attempted!=4*(b->next_sample+1) || b->completed!=b->attempted)
        return mt6762_gauge_probe_reject(b);
    b->active=0;b->armed=0;b->next_sample++;return 1;
}
static inline int mt6762_gauge_probe_deadline(uint64_t start,uint64_t interval,uint64_t *out)
{
    if(!out || !interval || UINT64_MAX-start<interval)return 0;
    *out=start+interval;return 1;
}
static inline int mt6762_gauge_probe_in_lease(uint64_t start,uint64_t deadline,uint64_t now)
{return deadline>start && now>=start && now<deadline;}
#endif
