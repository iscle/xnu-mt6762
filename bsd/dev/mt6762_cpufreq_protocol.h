/* Read-only MT6762 CPU clock and stock C62 SSPM table interpretation. */
#ifndef MT6762_CPUFREQ_PROTOCOL_H
#define MT6762_CPUFREQ_PROTOCOL_H
#include <stdint.h>
struct mt6762_pvt_opp { uint32_t khz,uv; uint8_t postdiv,clkdiv; };
struct mt6762_pvt_table { struct mt6762_pvt_opp opp[3][16]; };
/* C62 is selected by exact stock boot bin evidence, not generic SoC DT maxima.
 * Frequencies and divider methods are invariant; runtime EEM selectors vary. */
static const uint16_t mt6762_c62_mhz[3][16]={
    {2001,1961,1927,1897,1868,1838,1809,1779,1750,1617,1484,1351,1218,1085,979,900},
    {1500,1429,1367,1314,1261,1208,1155,1102,1050,948,846,745,643,542,501,400},
    {1048,997,953,915,877,839,801,763,724,658,592,525,459,392,339,300},
};
static const uint8_t mt6762_c62_postdiv[3][16]={
    {1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2},
    {2,2,2,2,2,2,2,2,2,2,2,4,4,4,4,4},
    {2,2,2,2,2,2,2,2,4,4,4,4,4,4,4,4},
};
static const uint8_t mt6762_c62_clkdiv[3][16]={
    {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1},
    {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,2},
    {1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2},
};
/* This validates representation only, not EEM calibration/firmware liveness. */
static inline int mt6762_pvt_decode(const uint32_t words[144],struct mt6762_pvt_table *out)
{
    struct mt6762_pvt_table t;
    if(!words || !out)return -1;
    for(unsigned d=0;d<3;d++) {
        if(words[d*36+32]!=0xffffffffu)return -2;
        for(unsigned i=0;i<16;i++) {
            uint32_t fv=words[d*36+i],method=words[d*36+16+i];
            uint32_t selector=(fv>>16)&0xfff;
            if((fv&0xf0000000) || selector>127 || (method&0xff00ff00) ||
               (fv&0xffff)!=mt6762_c62_mhz[d][i] ||
               (method&0xff)!=mt6762_c62_postdiv[d][i] ||
               ((method>>16)&0xff)!=mt6762_c62_clkdiv[d][i])return -3;
            t.opp[d][i].khz=(fv&0xffff)*1000;
            t.opp[d][i].uv=518750+selector*6250;
            t.opp[d][i].postdiv=(uint8_t)method;
            t.opp[d][i].clkdiv=(uint8_t)(method>>16);
        }
    }
    *out=t;return 0;
}
/* Nominal configured frequency from a stable register snapshot and 26 MHz
 * reference, not a hardware frequency-counter measurement. Reject bypass
 * muxes and unsupported/reserved dividers instead of assuming CPU PLL. */
static inline int mt6762_pll_khz(uint32_t con0,uint32_t con1,uint32_t power,
                                uint32_t ckdiv,uint32_t *khz)
{
    unsigned post=(con1>>24)&7,div=(ckdiv>>17)&31,num=1,den=1;
    uint32_t pcw=con1&0x3fffff;
    uint64_t rate;
    if(!khz || !(con0&1) || (power&3)!=1 || ((ckdiv>>9)&3)!=1 ||
       !pcw || post>4)return -1;
    /* Code 0 is the undivided boot encoding retained by this unit's exact
     * preloader. Its PLL setup leaves DIVSEL unchanged, and physical capture26
     * observes 0 on all three domains. Stock get_cur_phy_freq treats it as
     * unity. See hardware/cpu-power/CKDIV0.rst; do not extend stock's permissive
     * default to other unsupported encodings. */
    if(div==0) {num=1;den=1;}
    else if(div>=8 && div<=11) {num=12-div;den=4;}
    else if(div>=16 && div<=20) {num=21-div;den=5;}
    else if(div>=24 && div<=29) {num=30-div;den=6;}
    else return -1;
    rate=(uint64_t)pcw*26000*num/((uint64_t)16384*(1u<<post)*den);
    if(!rate || rate>UINT32_MAX)return -1;
    *khz=(uint32_t)rate;return 0;
}
static inline int mt6762_ppm_indices(uint32_t raw,unsigned *ceiling,unsigned *floor)
{
    unsigned limit=raw>>16,base=raw&0xffff;
    if(!ceiling || !floor || limit>15 || base>15 || limit>base)return -1;
    *ceiling=limit;*floor=base;return 0;
}
#endif
