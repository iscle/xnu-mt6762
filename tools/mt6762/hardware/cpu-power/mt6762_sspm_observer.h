/* Bounded passive observation of the exact stock SSPM AP interface.
 * No write callback, command, ACK clear, ownership or liveness inference.
 * Matching snapshots are representation evidence, not an atomic transaction. */
#ifndef MT6762_SSPM_OBSERVER_H
#define MT6762_SSPM_OBSERVER_H
#include <stdint.h>
#include "../../../../bsd/dev/mt6762_cpufreq_protocol.h"

enum { MT6762_OBS_CSRAM, MT6762_OBS_DATA, MT6762_OBS_CTRL, MT6762_OBS_GIC };
enum {
    MT6762_OBS_GUARDS=1, MT6762_OBS_PVT=2, MT6762_OBS_EEM=4,
    MT6762_OBS_PPM=8, MT6762_OBS_VOLT=16, MT6762_OBS_INDEX=32,
    MT6762_OBS_VOTE=64, MT6762_OBS_MAILBOX=128, MT6762_OBS_IRQ=256,
    MT6762_OBS_ALL=511, MT6762_OBS_WORDS=174
};
typedef int (*mt6762_sspm_observer_read)(void *,unsigned,uint32_t,uint32_t *);
struct mt6762_sspm_observation {
    uint32_t guards[5],pvt[144],eem[3],ppm[2],voltage[3],index[3],vote[3];
    uint32_t mailbox[9]; /* IN, OUT, then mailbox0 slots0..6. */
    uint32_t irq[2]; /* GICD ISENABLER7 / ISACTIVER7, observe INTID237 bit13. */
};
struct mt6762_sspm_observation_pair {
    struct mt6762_sspm_observation sample[2];
    unsigned stable_groups;
};
/* Exact whitelist shared by the hardware callback and the host verifier. */
static inline int mt6762_sspm_observer_address(unsigned region,uint32_t offset)
{
    if(offset&3)return 0;
    switch(region) {
    case MT6762_OBS_CSRAM:
        return offset<0x250 || offset==0x2a0 ||
            (offset>=0x300 && offset<=0x308) ||
            offset==0x320 || offset==0x324 ||
            (offset>=0x32c && offset<=0x334) ||
            (offset>=0x354 && offset<=0x35c) ||
            (offset>=0x3a4 && offset<=0x3ac);
    case MT6762_OBS_DATA:return offset<=24;
    case MT6762_OBS_CTRL:return offset==0 || offset==4;
    case MT6762_OBS_GIC:return offset==0x11c || offset==0x31c;
    default:return 0;
    }
}
static inline int mt6762_sspm_observer_words(mt6762_sspm_observer_read read,
    void *context,unsigned region,uint32_t offset,uint32_t *out,unsigned count)
{
    for(unsigned i=0;i<count;i++) {
        if(!mt6762_sspm_observer_address(region,offset+4*i) ||
           read(context,region,offset+4*i,&out[i]))return -1;
    }
    return 0;
}
static inline int mt6762_sspm_observe_once(mt6762_sspm_observer_read read,
    void *context,struct mt6762_sspm_observation *out)
{
    struct mt6762_sspm_observation s;
    if(!read || !out)return -1;
#define OBS(region,offset,member,count) \
    if(mt6762_sspm_observer_words(read,context,region,offset,s.member,count))return -1
    OBS(MT6762_OBS_CSRAM,0,guards,4);
    if(read(context,MT6762_OBS_CSRAM,0x2a0,&s.guards[4]))return -1;
    OBS(MT6762_OBS_CSRAM,0x10,pvt,144);
    OBS(MT6762_OBS_CSRAM,0x300,eem,3);
    OBS(MT6762_OBS_CSRAM,0x320,ppm,2);
    OBS(MT6762_OBS_CSRAM,0x32c,voltage,3);
    OBS(MT6762_OBS_CSRAM,0x354,index,3);
    OBS(MT6762_OBS_CSRAM,0x3a4,vote,3);
    OBS(MT6762_OBS_CTRL,0,mailbox,2);
    if(mt6762_sspm_observer_words(read,context,MT6762_OBS_DATA,0,s.mailbox+2,7))return -1;
    if(read(context,MT6762_OBS_GIC,0x11c,&s.irq[0]) ||
       read(context,MT6762_OBS_GIC,0x31c,&s.irq[1]))return -1;
#undef OBS
    *out=s;return 0;
}
static inline int mt6762_sspm_observer_equal(const uint32_t *a,const uint32_t *b,unsigned n)
{for(unsigned i=0;i<n;i++)if(a[i]!=b[i])return 0;return 1;}
/* Exactly two passes, at most348 read callbacks. No retries conceal a changing
 * controller. Failure leaves the caller's entire output unchanged. */
static inline int mt6762_sspm_observe_pair(mt6762_sspm_observer_read read,
    void *context,struct mt6762_sspm_observation_pair *out)
{
    struct mt6762_sspm_observation_pair p;
    if(!out || mt6762_sspm_observe_once(read,context,&p.sample[0]) ||
       mt6762_sspm_observe_once(read,context,&p.sample[1]))return -1;
    p.stable_groups=0;
#define EQ(member,n,flag) if(mt6762_sspm_observer_equal(p.sample[0].member,p.sample[1].member,n))p.stable_groups|=flag
    EQ(guards,5,MT6762_OBS_GUARDS); EQ(pvt,144,MT6762_OBS_PVT);
    EQ(eem,3,MT6762_OBS_EEM); EQ(ppm,2,MT6762_OBS_PPM);
    EQ(voltage,3,MT6762_OBS_VOLT); EQ(index,3,MT6762_OBS_INDEX);
    EQ(vote,3,MT6762_OBS_VOTE); EQ(mailbox,9,MT6762_OBS_MAILBOX);
    EQ(irq,2,MT6762_OBS_IRQ);
#undef EQ
    *out=p;return 0;
}
static inline int mt6762_sspm_observer_guards(const struct mt6762_sspm_observation_pair *p)
{
    static const uint32_t expected[5]={0x55aa55aa,0xaa55aa55,0x55aa55aa,0xaa55aa55,0x55aa55aa};
    return p && (p->stable_groups&MT6762_OBS_GUARDS) &&
        mt6762_sspm_observer_equal(p->sample[0].guards,expected,5);
}
/* Only the observed table representation matches C62. Guards are AP writes;
 * this does not establish controller initialization, bin, EEM or freshness. */
static inline int mt6762_sspm_observer_c62(const struct mt6762_sspm_observation_pair *p)
{
    struct mt6762_pvt_table table;
    return p && mt6762_sspm_observer_guards(p) &&
        (p->stable_groups&MT6762_OBS_PVT) && !mt6762_pvt_decode(p->sample[0].pvt,&table);
}
#endif
