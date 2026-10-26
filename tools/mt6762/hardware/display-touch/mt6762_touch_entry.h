/* SPDX-License-Identifier: MIT -- captured LK touch-bus admission only.
 * No rail claim: successful version and DMA transactions are still required. */
#ifndef MT6762_TOUCH_ENTRY_H
#define MT6762_TOUCH_ENTRY_H
#include <stdint.h>
typedef uint32_t (*mt6762_entry_read)(void *,uint32_t,unsigned);
#define MT6762_TOUCH_ENTRY_REGIONS 9
static inline uint32_t mt6762_touch_entry_base(unsigned index)
{
    static const uint32_t bases[MT6762_TOUCH_ENTRY_REGIONS]={
        0x10000000,0x10001000,0x10002000,0x10005000,0x1000b000,
        0x1000c000,0x0c000000,0x11007000,0x11000000};
    return index<MT6762_TOUCH_ENTRY_REGIONS?bases[index]:0;
}
struct mt6762_touch_entry_failure {uint32_t address,mask,expected,actual,pass,width;};
static inline int mt6762_touch_entry_detail(mt6762_entry_read read,void *ctx,
    struct mt6762_touch_entry_failure *failure)
{
    static const struct {uint32_t address,mask,value;unsigned width;} checks[]={
        {0x100000a0,0x87,2,4}, {0x10001090,1u<<11,0,4}, {0x10001094,1u<<18,0,4},
        {0x1000c26c,0xffffffff,0xff800081,4}, {0x1000c270,0xffffffff,0x00180000,4},
        {0x1000c278,0xffffffff,0x80000001,4},
        {0x100053a0,0xff00,0x1100,4}, {0x10005020,3u<<18,0,4},
        {0x10005220,3u<<18,3u<<18,4},
        {0x10002a30,(1u<<24)|(1u<<22),(1u<<24)|(1u<<22),4},
        {0x10002a40,(1u<<24)|(1u<<22),0,4},
        {0x10002a50,(1u<<24)|(1u<<22),(1u<<24)|(1u<<22),4},
        {0x10002a80,(1u<<11)|(1u<<9),(1u<<11)|(1u<<9),4},
        {0x10005450,0x0f000000,0,4}, {0x10005050,1u<<14,1u<<14,4},
        {0x10005150,1u<<14,1u<<14,4}, {0x10005250,1u<<14,1u<<14,4},
        {0x10005300,15,0,4}, {0x10005000,1,0,4}, {0x10005200,1,1,4},
        {0x1000b000,1,0,4}, {0x1000b080,1,1,4}, {0x1000b200,1,0,4}, {0x1000b400,1,0,4},
        {0x0c000000,0x80000000,0,4}, {0x0c00010c,1u<<20,0,4}, {0x0c00030c,1u<<20,0,4},
        {0x11007024,1,0,2}, {0x1100700c,0x1ff,0,2},
        {0x11000080,0xffffffff,0,4}, {0x11000088,0xffffffff,0,4},
        {0x1100009c,0xffffffff,0,4}, {0x110000a0,0xffffffff,0,4},
        {0x110000a4,0xffffffff,0,4}, {0x110000a8,0xffffffff,0,4},
        {0x110000d4,0xffffffff,0,4}, {0x110000d8,0xffffffff,0,4},
    };
    /* Clock checks come first, before accessing controller and DMA registers.
     * GIC pending116 is intentionally ignored; that line remains masked. */
    for(unsigned pass=0;pass<2;pass++)
        for(unsigned n=0;n<sizeof(checks)/sizeof(checks[0]);n++) {
            uint32_t actual=read(ctx,checks[n].address,checks[n].width);
            if((actual&checks[n].mask)!=checks[n].value) {
                if(failure)*failure=(struct mt6762_touch_entry_failure){checks[n].address,
                    checks[n].mask,checks[n].value,actual,pass,checks[n].width};
                return 0;
            }
        }
    return 1;
}
static inline int mt6762_touch_entry_ok(mt6762_entry_read read,void *ctx)
{return mt6762_touch_entry_detail(read,ctx,0);}
#endif
