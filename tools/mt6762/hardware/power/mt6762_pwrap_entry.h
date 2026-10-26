/* SPDX-License-Identifier: MIT -- narrow inherited LK WACS2 read admission.
 * Other masters, cipher, DIO, arbitration, clocks and PMIC state are preserved.
 * Exact LK tests RDATA.INIT_DONE at bit22; the legacy lab uses bit21. */
#ifndef MT6762_PWRAP_ENTRY_H
#define MT6762_PWRAP_ENTRY_H
#include <stdint.h>
typedef uint32_t (*mt6762_pwrap_entry_read)(void *,uint32_t);
static inline int mt6762_pwrap_entry_ok(mt6762_pwrap_entry_read read,void *ctx)
{
    static const struct {uint32_t address,mask,value;} checks[]={
        {0x10001090,2,0}, /* Clock gate first, before PWRAP access. */
        {0x1000d000,0xffffffff,0},{0x1000d004,0xffffffff,1},
        {0x1000d07c,0xffffffff,0},{0x1000d09c,0xffffffff,1},
        {0x1000d0a0,0xffffffff,1},{0x1000dc24,0x470000,0x400000},
    };
    for(unsigned pass=0;pass<2;pass++)
        for(unsigned n=0;n<sizeof(checks)/sizeof(checks[0]);n++)
            if((read(ctx,checks[n].address)&checks[n].mask)!=checks[n].value)return 0;
    return 1;
}
#endif
