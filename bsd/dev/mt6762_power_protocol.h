/* Bounded protocol shared with host fixtures. No board initialization. */
#ifndef MT6762_POWER_PROTOCOL_NATIVE_H
#define MT6762_POWER_PROTOCOL_NATIVE_H
#include <stdint.h>
#include "mt6762_bif_protocol.h"
struct mt6762_wacs_io {
    void *context;
    uint32_t (*read)(void *, uint32_t);
    void (*write)(void *, uint32_t, uint32_t);
    void (*delay_us)(void *, unsigned);
};
enum { MT6762_WACS_LEGACY21=1, MT6762_WACS_LK22=2 };
static inline int
mt6762_wacs_wait(const struct mt6762_wacs_io *io,unsigned profile,unsigned state,uint32_t *value)
{
    if(profile!=MT6762_WACS_LEGACY21 && profile!=MT6762_WACS_LK22)return -1;
    uint32_t initialized=1u<<(profile==MT6762_WACS_LK22?22:21);
    unsigned n;
    for(n=0;n<1000;n++) {
        *value=io->read(io->context,0xc24);
        if(!(*value&initialized)) return -2;
        if(((*value>>16)&7)==state) return 0;
        io->delay_us(io->context,10);
    }
    return -3;
}
static inline int
mt6762_wacs_transfer_profile(const struct mt6762_wacs_io *io,unsigned profile,int write,
                     uint16_t address,uint16_t *value)
{
    uint32_t status,command;
    uint16_t result;
    int e;
    if(!io || !io->read || !io->write || !io->delay_us || !value || (address&1) || (write!=0 && write!=1))return -1;
    if((e=mt6762_wacs_wait(io,profile,0,&status)))return e;
    command=((uint32_t)address>>1)<<16;
    if(write)command|=0x80000000u|*value;
    io->write(io->context,0xc20,command);
    if(write)return mt6762_wacs_wait(io,profile,0,&status);
    if((e=mt6762_wacs_wait(io,profile,6,&status)))return e;
    result=(uint16_t)status;
    io->write(io->context,0xc28,1);
    if((e=mt6762_wacs_wait(io,profile,0,&status)))return e;
    *value=result;return 0;
}
/* Retain the explicitly synthetic legacy contract for existing fixtures. */
static inline int
mt6762_wacs_transfer(const struct mt6762_wacs_io *io,int write,uint16_t address,uint16_t *value)
{return mt6762_wacs_transfer_profile(io,MT6762_WACS_LEGACY21,write,address,value);}
/* Recovered MT6357 ADC request/ready protocol. Outputs are committed only
 * after a non-rail, ready conversion. Caller owns channel serialization. */
struct mt6762_adc_io {
    void *context;
    int (*read)(void *, uint16_t, uint16_t *);
    int (*write)(void *, uint16_t, uint16_t);
    void (*delay_us)(void *, unsigned);
};
static int
mt6762_adc_sample(const struct mt6762_adc_io *io,unsigned channel,int *mv)
{
    uint16_t raw;
    unsigned bits,ratio;
    int e;
    if(!io || !io->read || !io->write || !io->delay_us || !mv)return -1;
    if(channel==1) {bits=15;ratio=3;}
    else if(channel==3) {bits=12;ratio=1;}
    else return -1;
    const struct mt6762_battery_adc_io fresh={io->context,io->read,io->write,io->delay_us};
    e=mt6762_battery_adc_fresh(&fresh,channel,&raw);
    if(e)return e;
    *mv=(int)(((uint32_t)raw*ratio*1800)>>bits);
    return 0;
}
/* A key must first be observed released; two equal samples debounce changes.
 * Invalid readings reset debounce and release a previously emitted key. */
struct mt6762_key_filter { unsigned armed, previous, count, down; };
static int
mt6762_key_update(struct mt6762_key_filter *k,int valid,unsigned pressed)
{
    if(!valid) {
        unsigned was=k->down;
        k->armed=k->previous=k->count=k->down=0;
        return was ? -1 : 0;
    }
    pressed=!!pressed;
    if(!k->armed) {
        if(!pressed)k->armed=1;
        return 0;
    }
    if(k->previous!=pressed) {k->previous=pressed;k->count=1;return 0;}
    if(k->count<2)k->count++;
    if(k->count==2 && k->down!=pressed) {k->down=pressed;return pressed?1:-1;}
    return 0;
}
#endif
