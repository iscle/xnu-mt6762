/* SPDX-License-Identifier: MIT -- capture26 inherited I2C5 entry admission.
 * Reads only. This is neither a charger identity check nor setup readback.
 * LK left a completed non-DMA write to address0x6a; GIC162 remains masked.
 * No clock, GPIO, IRQ, FIFO, controller, DMA or charger write occurs here.
 */
#ifndef MT6762_CHARGER_ENTRY_H
#define MT6762_CHARGER_ENTRY_H
#include <stdint.h>

typedef uint32_t (*mt6762_charger_entry_read)(void *,uint32_t,unsigned);
#define MT6762_CHARGER_I2C5_GATE_MASK (7u<<18)
static inline int mt6762_charger_i2c5_gates_ok(uint32_t infra4)
{return !(infra4&MT6762_CHARGER_I2C5_GATE_MASK);}
#define MT6762_CHARGER_ENTRY_REGIONS 8
static inline uint32_t mt6762_charger_entry_base(unsigned index)
{
    static const uint32_t bases[MT6762_CHARGER_ENTRY_REGIONS]={
        0x10000000,0x10001000,0x10002000,0x10005000,
        0x1000c000,0x0c000000,0x11016000,0x11000000};
    return index<MT6762_CHARGER_ENTRY_REGIONS?bases[index]:0;
}
struct mt6762_charger_entry_failure {
    uint32_t address,mask,expected,actual,pass,width;
};
static inline int mt6762_charger_entry_detail(mt6762_charger_entry_read read,
    void *context,struct mt6762_charger_entry_failure *failure)
{
    static const struct {uint32_t address,mask,value;unsigned width;} checks[]={
        /* Parent124.8MHz and gates first, before any controller/APDMA read.
         * IFR4 bits18/19/20 are I2C5, its arbiter and immediate-mode gates. */
        {0x100000a0,0x87,2,4},
        {0x10001090,1u<<11,0,4}, {0x10001094,1u<<18,0,4},
        {0x100010c8,MT6762_CHARGER_I2C5_GATE_MASK,0,4},
        {0x1000c26c,0xffffffff,0xff800081,4},
        {0x1000c270,0xffffffff,0x00180000,4},
        {0x1000c278,0xffffffff,0x80000001,4},
        /* GPIO48/49: SCL5/SDA5 function1, inputs high, inherited pads. */
        {0x10005360,0xff,0x11,4},
        {0x10005010,3u<<16,0,4}, {0x10005210,3u<<16,3u<<16,4},
        {0x10002610,7u<<18,0,4},
        {0x10002650,0x28,0x28,4}, {0x10002670,0x28,0,4},
        {0x10002690,0x28,0x28,4}, {0x100026c0,0x28000,0x28000,4},
        /* GIC pending162 is deliberately ignored: it is masked/inactive.
         * Do not acknowledge it as part of this read-only entry check. */
        {0x0c000000,0x80000000,0,4},
        {0x0c000114,1u<<2,0,4}, {0x0c000314,1u<<2,0,4},
        /* Exact pre-setup state, not the values written by initialize_bus.
         * STAT1 is completion; START0, no DMA addresses/lengths are active.
         * DIV4/HS8000 alone do not prove bus5 post-write behavior. */
        {0x11016004,0xffff,0x00d4,2},
        {0x11016008,0xffff,0x01f8,2},
        {0x1101600c,0xffff,0x0001,2},
        {0x11016010,0xffff,0x0028,2},
        {0x11016014,0xffff,0x0002,2},
        {0x11016018,0xffff,0x0001,2},
        {0x1101601c,0xffff,0x000a,2},
        {0x11016020,0xffff,0x0418,2},
        {0x11016024,0xffff,0x0000,2},
        {0x11016028,0xffff,0x8001,2},
        {0x1101602c,0xffff,0x0118,2},
        {0x11016030,0xffff,0x8000,2},
        {0x11016034,0xffff,0x01a3,2},
        {0x11016044,0xffff,0x0000,2},
        {0x11016048,0xffff,0x0004,2},
        {0x1101604c,0xffff,0x0000,2},
        {0x11000580,0xffffffff,0,4}, {0x11000584,0xffffffff,0,4},
        {0x11000588,0xffffffff,0,4}, {0x11000598,0xffffffff,8,4},
        {0x1100059c,0xffffffff,0,4}, {0x110005a0,0xffffffff,0,4},
        {0x110005a4,0xffffffff,0,4}, {0x110005a8,0xffffffff,0,4},
        {0x110005d4,0xffffffff,0,4}, {0x110005d8,0xffffffff,0,4},
    };
    if(!read)return 0;
    for(unsigned pass=0;pass<2;pass++)
        for(unsigned n=0;n<sizeof(checks)/sizeof(checks[0]);n++) {
            uint32_t actual=read(context,checks[n].address,checks[n].width);
            if((actual&checks[n].mask)!=checks[n].value) {
                if(failure)*failure=(struct mt6762_charger_entry_failure){
                    checks[n].address,checks[n].mask,checks[n].value,
                    actual,pass,checks[n].width};
                return 0;
            }
        }
    return 1;
}
static inline int mt6762_charger_entry_ok(mt6762_charger_entry_read read,void *context)
{return mt6762_charger_entry_detail(read,context,0);}
#endif
