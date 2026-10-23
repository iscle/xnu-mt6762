#include "opp_policy.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    struct mt6762_nominal_opp o={0};
    /* Actual policy vectors cap maxima despite generic DT claiming higher. */
    assert(!mt6762_c62_select(MT6762_CPU0,2500000,900000,2500000,2500000,&o));
    assert(o.khz==2001000 && o.nominal_uv==1118750 && o.index==0);
    assert(!mt6762_c62_select(MT6762_CPU4,2000000,400000,2000000,2000000,&o));
    assert(o.khz==1500000 && o.nominal_uv==1118750 && o.postdiv==2);
    assert(!mt6762_c62_select(MT6762_CPU0,2001000,900000,2001000,1500000,&o));
    assert(o.khz==1484000 && o.nominal_uv==737500 && o.postdiv==2);
    assert(!mt6762_c62_select(MT6762_CPU4,510000,400000,1500000,1500000,&o));
    assert(o.khz==501000 && o.nominal_uv==631250);
    assert(!mt6762_c62_select(MT6762_CCI,300000,300000,1048000,1048000,&o));
    assert(o.index==15 && o.clkdiv==2 && o.postdiv==4);
    o.khz=123;
    assert(mt6762_c62_select(MT6762_CPU0,2001000,900000,2001000,0,&o)==-1&&o.khz==123);
    assert(mt6762_c62_select(MT6762_CPU0,899999,900000,2001000,2001000,&o)==-1);
    assert(mt6762_c62_select((enum mt6762_domain)3,2001000,1,2001000,2001000,&o)==-1);
    uint8_t indices[3]={15,0,15};uint32_t v=0;
    assert(!mt6762_c62_shared_voltage(indices,&v)&&v==1118750);
    indices[1]=15;indices[2]=4;
    assert(!mt6762_c62_shared_voltage(indices,&v)&&v==950000);
    indices[2]=16;v=123;
    assert(mt6762_c62_shared_voltage(indices,&v)==-1&&v==123);
    uint8_t s=0;
    assert(!mt6357_selector_for_window(1118750,1118750,&s,&v)&&s==96&&v==1118750);
    assert(!mt6357_selector_for_window(600001,606250,&s,&v)&&s==14&&v==606250);
    v=123;
    assert(mt6357_selector_for_window(1120000,1120000,&s,&v)==-1&&v==123);
    assert(mt6357_selector_for_window(1,600000,&s,&v)==-1);
    uint32_t off,word;
    assert(!mt6762_sspm_vote(MT6762_CPU0,15,1,&off,&word)&&off==0x3a4&&word==0x1f);
    assert(!mt6762_sspm_vote(MT6762_CPU4,0,255,&off,&word)&&off==0x3a8&&word==0xff0);
    assert(mt6762_sspm_vote(MT6762_CPU4,16,1,&off,&word)==-1);
    assert(mt6762_sspm_vote(MT6762_CPU4,0,0,&off,&word)==-1);
    puts("PASS: C62 OPP caps, shared nominal VPROC demand, PMIC rounding and SSPM word encoding");
}
