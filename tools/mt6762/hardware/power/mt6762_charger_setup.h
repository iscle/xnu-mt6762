/* SPDX-License-Identifier: MIT -- I2C5 capture31 post-write profile.
 * Separate from bus0's capture20 matcher and bus5's inherited entry check.
 * Include the canonical mt6762_i2c.h first. No hardware access or grants.
 */
#ifndef MT6762_CHARGER_SETUP_H
#define MT6762_CHARGER_SETUP_H
#include <stddef.h>
#include <stdint.h>
#define MT6762_CHARGER_READONLY_LIMIT 6u
struct mt6762_charger_setup_readback {
    uint16_t div,timing,ltiming,hs,io,ext,delay,timeout;
};
static inline int mt6762_charger_setup_ok(unsigned parent_index,uint32_t parent_hz,
    uint32_t bus_hz,const struct mtk_i2c_timing *t,
    const struct mt6762_charger_setup_readback *r)
{
    /* Exact requested configuration and actual bus5 readbacks, after writes.
     * Capture31/Image37/kernel52 independently establishes DIV4 and HS8000.
     * Entry TIMING418/IO1a3/TIMEOUT0 must never satisfy this profile. */
    return t && r && parent_index==2 && parent_hz==124800000 && bus_hz==100000 &&
        t->clock_div==0x0404 && t->timing==0x0419 && t->ltiming==0x0118 &&
        t->ext==0x8001 && t->timeout==0x0190 &&
        r->div==4 && r->timing==0x0419 && r->ltiming==0x0118 && r->hs==0x8000 &&
        r->io==3 && r->ext==0x8001 && r->delay==0xa && r->timeout==0x0190;
}
static inline int mt6762_charger_readonly_request_ok(unsigned index,unsigned address,
    const void *tx,size_t nt,size_t nr)
{
    static const uint8_t registers[MT6762_CHARGER_READONLY_LIMIT]={3,1,0,3,1,0};
    return index<MT6762_CHARGER_READONLY_LIMIT && address==0x6a && tx && nt==1 && nr==1 &&
        *(const uint8_t *)tx==registers[index];
}
#endif
