/* SPDX-License-Identifier: MIT -- captured inherited keypad, read-only polling.
 * Stock DT: fixed26MHz clock, matrix indices0/1, GIC INTID212.
 * MT6765 pin mapping: GPIO92 row0, GPIO93/94 columns0/1; capture20 matches.
 * Captures19/20: enabled, debounce0x400, selection0x1c70, masked/inactive IRQ.
 * Pending IRQ is allowed: polling never acknowledges or unmasks it.
 */
#ifndef MT6762_KEYS_ENTRY_H
#define MT6762_KEYS_ENTRY_H
#include <stdint.h>
static inline int mt6762_keys_entry_ok(
    uint32_t (*read)(void *,uint32_t,unsigned),void *context)
{
    if(!read)return 0;
    for(unsigned pass=0;pass<2;pass++) {
        if(read(context,0x0c000118,4)&(1u<<20))return 0;
        if(read(context,0x0c000318,4)&(1u<<20))return 0;
        if((read(context,0x100053b0,4)&0x07770000)!=0x01110000)return 0;
        if(read(context,0x10010024,2)!=1 ||
           read(context,0x10010018,2)!=0x400 ||
           read(context,0x10010020,2)!=0x1c70)return 0;
    }
    return 1;
}
#endif
