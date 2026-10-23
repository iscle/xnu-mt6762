#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../../../bsd/dev/mt6762_cpufreq_protocol.h"
#include "pvt_fixture.h"
static void table_tests(void)
{
    uint32_t words[144];struct mt6762_pvt_table t,before;
    memcpy(words,pvt_fixture,sizeof(words));
    assert(!mt6762_pvt_decode(words,&t));
    assert(t.opp[0][0].khz==2001000 && t.opp[0][0].uv==1118750);
    assert(t.opp[1][15].khz==400000 && t.opp[1][15].postdiv==4 && t.opp[1][15].clkdiv==2);
    assert(t.opp[2][15].khz==300000 && t.opp[2][15].uv==600000);
    words[0]=(80u<<16)|2001; /* independent runtime EEM selector, not nominal */
    assert(!mt6762_pvt_decode(words,&t) && t.opp[0][0].uv==1018750);
    before=t;
    unsigned offsets[]={0,0,16,32};uint32_t bad[]={0x600000, (128u<<16)|2001,0x01010001,0};
    for(unsigned i=0;i<4;i++) {
        memcpy(words,pvt_fixture,sizeof(words));words[offsets[i]]=bad[i];
        assert(mt6762_pvt_decode(words,&t));assert(!memcmp(&t,&before,sizeof(t)));
    }
    assert(mt6762_pvt_decode(NULL,&t));
}
static void clock_tests(void)
{
    uint32_t khz=999,ck=(1u<<9)|(8u<<17);
    assert(!mt6762_pll_khz(1,0x100000,1,ck,&khz) && khz==1664000);
    assert(!mt6762_pll_khz(1,0x1100000,1,ck,&khz) && khz==832000);
    assert(!mt6762_pll_khz(1,0x1100000,1,(1u<<9)|(10u<<17),&khz) && khz==416000);
    assert(!mt6762_pll_khz(1,0x100000,1,(1u<<9)|(9u<<17),&khz) && khz==1248000);
    assert(!mt6762_pll_khz(1,0x100000,1,(1u<<9)|(17u<<17),&khz) && khz==1331200);
    assert(!mt6762_pll_khz(1,0x100000,1,(1u<<9)|(29u<<17),&khz) && khz==277333);
    assert(mt6762_pll_khz(0,0x100000,1,ck,&khz) && khz==277333);
    assert(mt6762_pll_khz(1,0x100000,3,ck,&khz) && khz==277333);
    assert(mt6762_pll_khz(1,0x100000,0,ck,&khz));
    assert(mt6762_pll_khz(1,0x100000,1,8u<<17,&khz));
    assert(mt6762_pll_khz(1,0x100000,1,(2u<<9)|(8u<<17),&khz));
    assert(mt6762_pll_khz(1,0x5100000,1,ck,&khz));
    assert(mt6762_pll_khz(1,0x100000,1,(1u<<9)|(12u<<17),&khz));
    assert(mt6762_pll_khz(1,0,1,ck,&khz));
}
static void caps_tests(void)
{
    unsigned cap=999,floor=999;
    assert(!mt6762_ppm_indices(15,&cap,&floor) && cap==0 && floor==15);
    assert(!mt6762_ppm_indices((7u<<16)|12,&cap,&floor) && cap==7 && floor==12);
    assert(mt6762_ppm_indices((13u<<16)|12,&cap,&floor) && cap==7 && floor==12);
    assert(mt6762_ppm_indices(16,&cap,&floor));
}
int main(void) {table_tests();clock_tests();caps_tests();puts("native CPU PLL, runtime SSPM table, PPM validation: PASS");return 0;}
