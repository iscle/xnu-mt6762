/* SPDX-License-Identifier: MIT
 * Read-only producer for the exact LK's completed synchronous eMMC handoff.
 * No card command, controller write, pointer following or guessed tuning.
 * The kernel must independently check rails and live CMD13/EXT_CSD before
 * publishing its read-only disk. See audit_lk_msdc.py and capture19 evidence.
 */
#ifndef MT6762_NATIVE_STORAGE_H
#define MT6762_NATIVE_STORAGE_H
#include <stdint.h>
#include "../../../bsd/dev/mt6762_msdc_clock.h"

struct mt6762_storage_profile {
    uint32_t sectors,ocr,rca,cfg,sdc_cfg,pad_drive,hclk_hz,card_clock_hz;
    uint32_t pll[6],top_tune[12],controller_tune[18];
};
_Static_assert(sizeof(struct mt6762_storage_profile)==44*4,"storage profile layout");
typedef uint32_t (*mt6762_storage_read)(void *,uint32_t);

static inline int mt6762_storage_snapshot(mt6762_storage_read read,void *ctx,
    struct mt6762_storage_profile *p)
{
#define R(a) read(ctx,(a))
    /* Clock-gated register reads are forbidden until both parents/gates pass. */
    uint32_t top=R(0x10000070),parent,hclk;
    if((top&0x8783)!=0x101 || (R(0x10001094)&4) || (R(0x100010c8)&0x200))return 0;
    static const uint32_t plls[]={0x1000c27c,0x1000c280,0x1000c288,
        0x1000c23c,0x1000c240,0x1000c248};
    for(unsigned i=0;i<6;i++)p->pll[i]=R(plls[i]);
    if(mt6762_msdc_pll_hz(p->pll[0],p->pll[1],p->pll[2],&parent) ||
        !(p->pll[3]&(1u<<23)) ||
        mt6762_msdc_pll_hz(p->pll[3],p->pll[4],p->pll[5],&hclk))return 0;
    p->hclk_hz=hclk/4;
    /* The fixed getter/code metadata belongs to the independently hashed LK.
     * No function or data pointer read here is ever used as an address. */
    static const uint32_t getters[]={0x4a0301c3,0x00c0eb03,0x4410447a,0xbf004770,0xfb12c,
        0x4a030203,0x2080ebc3,0x4410447a,0xbf004770,0xfb228};
    for(unsigned i=0;i<10;i++)if(R(0x4804bb18+4*i)!=getters[i])return 0;
    static const uint32_t completion[][2]={
        {0x48050fc4,0x43f0e92d},{0x48051010,0xf7ff9603},
        {0x48050e64,0xf7ff4650},{0x48050e6c,0x465031ff},
        {0x48050e70,0xff40f7ff},{0x48050e78,0xff12f7ff},
        {0x48050cd0,0x68133098},{0x48050cd4,0xd4fc07db},
        {0x48050cdc,0x4150f44f},{0x48050ce4,0xf7fd6023}};
    for(unsigned i=0;i<sizeof(completion)/sizeof(completion[0]);i++)
        if(R(completion[i][0])!=completion[i][1])return 0;
    if(R(0x48146c50)!=0x48146d60 || R(0x48146d60)!=0x48146c50 ||
        R(0x48146c78)!=0x11230000 || R(0x48146c7c)!=0x11cd0000 ||
        R(0x48146c94)!=512 || R(0x48146d68)!=512 ||
        R(0x48146ccc)!=0x48050fc5 || R(0x48146d7c)!=1)return 0;
    p->sectors=R(0x48146d64);p->ocr=R(0x48146d6c);p->rca=R(0x48146d78);
    uint32_t state=R(0x48146d80);
    if(!p->sectors || p->sectors>0x7fffffff || (p->ocr&0xc0000000)!=0xc0000000 ||
        !p->rca || p->rca>0xffff || !(state&0x10) || state>>16!=1)return 0;
    /* GIC111 level, disabled, inactive, without a pending completion. */
    uint32_t irq=1u<<15;
    if((R(0x0c000000)&0x80000000u) || (R(0x0c00010c)&irq) ||
        (R(0x0c00020c)&irq) || (R(0x0c00030c)&irq) ||
        (R(0x0c000c18)&0xc0000000u))return 0;
    p->cfg=R(0x11230000);p->sdc_cfg=R(0x11230030);
    if(p->cfg!=0x02200199 || p->sdc_cfg!=0x09020000 ||
        R(0x1123000c) || R(0x11230010) || (R(0x1123003c)&3) ||
        (R(0x1123009c)&1) || (R(0x11230014)&0x80ff00ffu) ||
        (R(0x11230204)&1) || (R(0x1123023c)&3) || (R(0x11230670)&7)!=4 ||
        mt6762_msdc_sclk_hz(parent,p->cfg,&p->card_clock_hz) ||
        p->card_clock_hz>52000000)return 0;
    uint32_t trap=R(0x100056f0)&0x6000;
    p->pad_drive=R(0x10002000)&0x1fffc0;
    if((R(0x100053f0)&0x77777700)!=(trap?0x11111100:0x22222200) ||
        (R(0x10005400)&0x00777777)!=(trap?0x00111111:0x00222222) ||
        p->pad_drive!=0x49240 || (R(0x10002030)&0xfff)!=0x401 ||
        (R(0x10002050)&0xfff)!=0xbfe || (R(0x10002060)&0xfff)!=0x401 ||
        (R(0x10002090)&0x00fffff0) || (R(0x10002070)&0xfffffffc))return 0;
    for(unsigned i=0;i<12;i++)p->top_tune[i]=R(0x11cd0000+4*i);
    static const uint16_t tune[]={0x04,0xb0,0xb4,0xb8,0xf0,0xf4,0xf8,0xfc,
        0x100,0x104,0x180,0x184,0x188,0x18c,0x190,0x194,0x198,0x19c};
    for(unsigned i=0;i<18;i++)p->controller_tune[i]=R(0x11230000+tune[i]);
    if(top!=R(0x10000070) || (R(0x10001094)&4) || (R(0x100010c8)&0x200) ||
        trap!=(R(0x100056f0)&0x6000))return 0;
    for(unsigned i=0;i<6;i++)if(p->pll[i]!=R(plls[i]))return 0;
    return 1;
#undef R
}
static inline int mt6762_storage_profile_read(mt6762_storage_read read,void *ctx,
    struct mt6762_storage_profile *out)
{
    if(!read || !out)return 0;
    struct mt6762_storage_profile first={0},second={0};
    if(!mt6762_storage_snapshot(read,ctx,&first) ||
        !mt6762_storage_snapshot(read,ctx,&second))return 0;
    /* All fields are uint32_t; compare object bytes without aliasing casts. */
    const unsigned char *a=(const void *)&first,*b=(const void *)&second;
    for(unsigned i=0;i<sizeof(first);i++)if(a[i]!=b[i])return 0;
    *out=first;return 1;
}
#endif
