#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "mt6762_sspm_observer.h"
#include "pvt_fixture.h"

struct fixture {
    uint32_t sram[0x500/4],data[7],ctrl[2],gic[0x400/4];
    unsigned reads,fail_at,change_at,regions[MT6762_OBS_WORDS],offsets[MT6762_OBS_WORDS];
};
static int read_word(void *context,unsigned region,uint32_t offset,uint32_t *out)
{
    struct fixture *f=context;
    uint32_t *bank;
    assert(mt6762_sspm_observer_address(region,offset));
    unsigned n=++f->reads;
    if(n<=MT6762_OBS_WORDS) {f->regions[n-1]=region;f->offsets[n-1]=offset;}
    if(n==f->fail_at)return -1;
    switch(region) {
    case MT6762_OBS_CSRAM:bank=f->sram;break;
    case MT6762_OBS_DATA:bank=f->data;break;
    case MT6762_OBS_CTRL:bank=f->ctrl;break;
    case MT6762_OBS_GIC:bank=f->gic;break;
    default:assert(0);return -1;
    }
    *out=bank[offset/4]^(n==f->change_at?1u:0u);return 0;
}
static void init(struct fixture *f)
{
    memset(f,0,sizeof(*f));
    f->sram[0]=f->sram[2]=f->sram[0x2a0/4]=0x55aa55aa;
    f->sram[1]=f->sram[3]=0xaa55aa55;
    memcpy(f->sram+4,pvt_fixture,sizeof(pvt_fixture));
    f->sram[0x320/4]=f->sram[0x324/4]=15;
    f->sram[0x354/4]=10;f->sram[0x358/4]=15;f->sram[0x35c/4]=10;
    f->sram[0x3a4/4]=0xffa; /* Submitted vote, no inferred ACK. */
    f->ctrl[0]=0x80000003;f->ctrl[1]=0x40000003; /* Pending traffic retained. */
    f->gic[0x11c/4]=f->gic[0x31c/4]=1u<<13; /* Enabled/active is observable. */
    for(unsigned i=0;i<7;i++)f->data[i]=0x12340000+i;
}
static unsigned group(unsigned region,unsigned offset)
{
    if(region==MT6762_OBS_GIC)return MT6762_OBS_IRQ;
    if(region!=MT6762_OBS_CSRAM)return MT6762_OBS_MAILBOX;
    if(offset<16 || offset==0x2a0)return MT6762_OBS_GUARDS;
    if(offset<0x250)return MT6762_OBS_PVT;
    if(offset<0x310)return MT6762_OBS_EEM;
    if(offset<0x32c)return MT6762_OBS_PPM;
    if(offset<0x354)return MT6762_OBS_VOLT;
    if(offset<0x3a4)return MT6762_OBS_INDEX;
    return MT6762_OBS_VOTE;
}
int main(void)
{
    struct fixture f,original;
    struct mt6762_sspm_observation_pair p,unchanged;
    _Static_assert(sizeof(p.sample[0])==MT6762_OBS_WORDS*4,"unexpected snapshot padding");
    init(&f);original=f;
    assert(!mt6762_sspm_observe_pair(read_word,&f,&p));
    assert(f.reads==2*MT6762_OBS_WORDS && p.stable_groups==MT6762_OBS_ALL);
    assert(mt6762_sspm_observer_guards(&p) && mt6762_sspm_observer_c62(&p));
    assert(!memcmp(&f,&original,offsetof(struct fixture,reads)));
    assert(p.sample[0].mailbox[0]==0x80000003 && p.sample[0].mailbox[1]==0x40000003);
    assert(p.sample[0].irq[0]==(1u<<13) && p.sample[0].irq[1]==(1u<<13));
    /* Exact whitelist: every permitted word is read once per pass; no status
     * acknowledgement, reset, command, arbitrary pointer or ring traversal. */
    unsigned allowed=0;
    for(unsigned region=0;region<4;region++)for(unsigned offset=0;offset<0x1400;offset++) {
        if(!mt6762_sspm_observer_address(region,offset))continue;
        unsigned found=0;allowed++;
        for(unsigned i=0;i<MT6762_OBS_WORDS;i++)
            found+=f.regions[i]==region && f.offsets[i]==offset;
        assert(found==1);
    }
    assert(allowed==MT6762_OBS_WORDS);
    assert(!mt6762_sspm_observer_address(4,0));
    assert(!mt6762_sspm_observer_address(0,0xfffffffc));
    /* Every read can fail, including the final read of pass2; no partial or
     * previous validity may replace the caller's output. */
    memset(&unchanged,0xa5,sizeof(unchanged));
    for(unsigned fail=1;fail<=2*MT6762_OBS_WORDS;fail++) {
        init(&f);f.fail_at=fail;p=unchanged;
        assert(mt6762_sspm_observe_pair(read_word,&f,&p)==-1);
        assert(f.reads==fail && !memcmp(&p,&unchanged,sizeof(p)));
    }
    /* Change each captured word in pass2: exactly its group loses stability.
     * This also covers changes confined to a table tail or unrelated IRQ bit. */
    for(unsigned word=0;word<MT6762_OBS_WORDS;word++) {
        init(&f);f.change_at=MT6762_OBS_WORDS+word+1;
        assert(!mt6762_sspm_observe_pair(read_word,&f,&p));
        unsigned expected=MT6762_OBS_ALL^group(f.regions[word],f.offsets[word]);
        assert(p.stable_groups==expected && f.reads==2*MT6762_OBS_WORDS);
    }
    memset(&f,0,sizeof(f));
    assert(!mt6762_sspm_observe_pair(read_word,&f,&p));
    assert(p.stable_groups==MT6762_OBS_ALL);
    assert(!mt6762_sspm_observer_guards(&p) && !mt6762_sspm_observer_c62(&p));
    init(&f);f.sram[4]^=1;
    assert(!mt6762_sspm_observe_pair(read_word,&f,&p));
    assert(mt6762_sspm_observer_guards(&p) && !mt6762_sspm_observer_c62(&p));
    /* Valid representation can coexist with pending EEM, invalid indices and
     * active IRQ/traffic. It must not be presented as firmware readiness. */
    init(&f);f.sram[0x300/4]=1;f.sram[0x354/4]=0xffffffff;
    assert(!mt6762_sspm_observe_pair(read_word,&f,&p));
    assert(mt6762_sspm_observer_c62(&p) && p.sample[0].eem[0]==1);
    assert(p.sample[0].index[0]==0xffffffff && p.sample[0].mailbox[0]==0x80000003);
    p=unchanged;f.reads=0;
    assert(mt6762_sspm_observe_pair(NULL,&f,&p)==-1 && !f.reads);
    assert(!memcmp(&p,&unchanged,sizeof(p)));
    assert(mt6762_sspm_observe_pair(read_word,&f,NULL)==-1 && !f.reads);
    puts("SSPM passive observer: 174-address whitelist, 348 injected read failures, 174 changing-word pairs, no writes: PASS");
    return 0;
}
