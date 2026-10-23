/* Bounded protocol shared with host fixtures. No board initialization. */
#ifndef MT6762_POWER_PROTOCOL_NATIVE_H
#define MT6762_POWER_PROTOCOL_NATIVE_H
#include <stdint.h>
struct mt6762_wacs_io {
    void *context;
    uint32_t (*read)(void *, uint32_t);
    void (*write)(void *, uint32_t, uint32_t);
    void (*delay_us)(void *, unsigned);
};
static int
mt6762_wacs_wait(const struct mt6762_wacs_io *io,unsigned state,uint32_t *value)
{
    unsigned n;
    for(n=0;n<1000;n++) {
        *value=io->read(io->context,0xc24);
        if(!(*value&(1u<<21))) return -2;
        if(((*value>>16)&7)==state) return 0;
        io->delay_us(io->context,10);
    }
    return -3;
}
static int
mt6762_wacs_transfer(const struct mt6762_wacs_io *io,int write,
                     uint16_t address,uint16_t *value)
{
    uint32_t status,command;
    uint16_t result;
    int e;
    if(!io || !io->read || !io->write || !io->delay_us || !value || (address&1))return -1;
    if((e=mt6762_wacs_wait(io,0,&status)))return e;
    command=((uint32_t)address>>1)<<16;
    if(write)command|=0x80000000u|*value;
    io->write(io->context,0xc20,command);
    if(write)return mt6762_wacs_wait(io,0,&status);
    if((e=mt6762_wacs_wait(io,6,&status)))return e;
    result=(uint16_t)status;
    io->write(io->context,0xc28,1);
    if((e=mt6762_wacs_wait(io,0,&status)))return e;
    *value=result;return 0;
}
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
    uint16_t raw,output;
    unsigned bits,ratio,wait_us;
    int e;
    if(!io || !io->read || !io->write || !io->delay_us || !mv)return -1;
    if(channel==1) {output=0x108a;bits=15;ratio=3;wait_us=1280;}
    else if(channel==3) {output=0x108e;bits=12;ratio=1;wait_us=80;}
    else return -1;
    if((e=io->write(io->context,0x110e,(uint16_t)(1u<<channel))))return e;
    io->delay_us(io->context,wait_us);
    for(unsigned n=0;n<160;n++) {
        if((e=io->read(io->context,output,&raw)))return e;
        if(raw&0x8000) {
            raw&=(uint16_t)((1u<<bits)-1);
            if(!raw || raw==((1u<<bits)-1))return -4;
            *mv=(int)(((uint32_t)raw*ratio*1800)>>bits);
            return 0;
        }
        io->delay_us(io->context,200);
    }
    return -3;
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
