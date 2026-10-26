/* SPDX-License-Identifier: MIT -- exact measured standard-mode readback. */
#ifndef MT6762_I2C_NATIVE_SETUP_H
#define MT6762_I2C_NATIVE_SETUP_H
/* Include the canonical mt6762_i2c.h before this header. */
static inline int mt6762_i2c_setup_ok(const struct mtk_i2c_timing *t,
    unsigned inherited_profile,uint16_t div,uint16_t timing,uint16_t ltiming,
    uint16_t hs,uint16_t io,uint16_t ext,uint16_t delay,uint16_t timeout)
{
    if(!t || inherited_profile>1)return 0;
    uint16_t expected_div=t->clock_div,expected_hs=0;
    if(inherited_profile) {
        /* Physical capture20: the vendor-style0x0404 write reads0x0004,
         * HS written0 retains0x8000. All other programmed fields match.
         * Admit only this measured divider; do not mask unknown bits/rates. */
        if(t->clock_div!=0x0404)return 0;
        expected_div=0x0004;expected_hs=0x8000;
    }
    return div==expected_div && timing==t->timing && ltiming==t->ltiming &&
        hs==expected_hs && io==3 && ext==t->ext && delay==0xa && timeout==t->timeout;
}
#endif
