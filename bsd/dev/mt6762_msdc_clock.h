/* SPDX-License-Identifier: MIT
 * Read-only rate arithmetic from the exact stock PLL descriptor/recalc code
 * and MSDC clock programming path. This does not configure or prove PLL lock. */
#ifndef MT6762_MSDC_CLOCK_H
#define MT6762_MSDC_CLOCK_H
#include <stdint.h>
static inline int mt6762_msdc_pll_hz(uint32_t con0,uint32_t con1,
    uint32_t power,uint32_t *hz)
{
    if(!hz || !(con0&1) || (power&3)!=1 || !(con1&0x3fffff))return -1;
    uint64_t vco=(26000000ULL*(con1&0x3fffff)+16383)/16384;
    unsigned post=1u<<((con1>>24)&7);
    uint64_t result=(vco+post-1)/post;
    if(!result || result>UINT32_MAX)return -1;
    *hz=(uint32_t)result;
    return 0;
}
static inline int mt6762_msdc_sclk_hz(uint32_t parent,uint32_t cfg,uint32_t *hz)
{
    unsigned mode=(cfg>>20)&3,div=(cfg>>8)&0xfff,hs400=(cfg>>22)&1;
    uint32_t denominator=0;
    if(!parent || !hz || (mode!=3 && hs400))return -1;
    if(mode==0)denominator=div?4*div:2;
    else if(mode==1) {if(div)return -1;denominator=1;}
    else if(mode==2) {
        /* Exact inherited LK/stock traced forms only. Do not infer untraced
         * odd-divider round-down behavior from a related controller. */
        if(div>1)return -1;
        denominator=div?8:4;
    } else {
        if(div)return -1;
        denominator=hs400?2:4;
    }
    uint32_t result=parent/denominator;
    if(!result)return -1;
    *hz=result;
    return 0;
}
/* Selected board I/O supply is1.8V. Reject1.2V-only capability claims.
 * mode is the admitted controller CKMOD, not EXT_CSD BUS_WIDTH: byte183
 * is write-only and cannot establish the card's active width or DDR mode.
 * The caller requires inherited8-bit SDC_CFG and a successful data transfer. */
static inline int mt6762_msdc_card_rate_ok(unsigned timing,unsigned mode,
    unsigned card_type,uint32_t hz)
{
    if(!hz)return 0;
    if(timing==1 && mode<2) {
        unsigned maximum=(card_type&2)?52000000:((card_type&1)?26000000:0);
        return hz<=maximum;
    }
    if(timing==1 && mode==2)return (card_type&4) && hz<=52000000;
    if(timing==2 && mode<2)return (card_type&16) && hz<=200000000;
    if(timing==3 && mode==3)return (card_type&64) && hz<=200000000;
    return 0;
}
#endif
