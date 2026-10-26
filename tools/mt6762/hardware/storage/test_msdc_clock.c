/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdio.h>
#include "../../../../bsd/dev/mt6762_msdc_clock.h"
int main(void)
{
    uint32_t hz=123;
    assert(mt6762_msdc_pll_hz(0,0x820ec4ec,1,&hz)<0 && hz==123);
    assert(mt6762_msdc_pll_hz(1,0x820ec4ec,3,&hz)<0 && hz==123);
    assert(!mt6762_msdc_pll_hz(1,0x820ec4ec,1,&hz) && hz==383999878);
    /* Exact22-bit PCW,8integerbits,26MHz reference; ceiling twice. */
    assert(!mt6762_msdc_pll_hz(1,0x02100000,1,&hz) && hz==416000000);
    assert(!mt6762_msdc_sclk_hz(400000000,0x89,&hz) && hz==200000000);
    assert(!mt6762_msdc_sclk_hz(400000000,0x289,&hz) && hz==50000000);
    assert(!mt6762_msdc_sclk_hz(400000000,0x200189,&hz) && hz==50000000);
    assert(!mt6762_msdc_sclk_hz(400000000,0x700089,&hz) && hz==200000000);
    assert(!mt6762_msdc_sclk_hz(400000000,0x300089,&hz) && hz==100000000);
    hz=123;
    assert(mt6762_msdc_sclk_hz(400000000,0x200289,&hz)<0 && hz==123);
    assert(mt6762_msdc_sclk_hz(400000000,0x300189,&hz)<0 && hz==123);
    assert(mt6762_msdc_sclk_hz(400000000,0x400089,&hz)<0 && hz==123);
    assert(mt6762_msdc_card_rate_ok(1,2,0x56,50000000));
    assert(!mt6762_msdc_card_rate_ok(1,2,0x56,200000000));
    assert(mt6762_msdc_card_rate_ok(2,0,0x56,200000000));
    assert(!mt6762_msdc_card_rate_ok(2,0,0x56,200000001));
    assert(!mt6762_msdc_card_rate_ok(2,0,0x20,200000000));
    assert(!mt6762_msdc_card_rate_ok(3,4,0x56,200000000));
    assert(mt6762_msdc_card_rate_ok(1,0,1,26000000));
    assert(!mt6762_msdc_card_rate_ok(1,0,1,26000001));
    assert(mt6762_msdc_card_rate_ok(1,1,2,52000000));
    assert(mt6762_msdc_card_rate_ok(3,3,64,200000000));
    assert(!mt6762_msdc_card_rate_ok(3,3,128,200000000));
    assert(!mt6762_msdc_card_rate_ok(2,2,0xff,200000000));
    assert(!mt6762_msdc_card_rate_ok(1,3,0xff,50000000));
    assert(!mt6762_msdc_card_rate_ok(3,0,0xff,200000000));
    puts("PASS: exact stock MSDCPLL/rate arithmetic, narrow divider admission and card timing/capability limits");
    return 0;
}
