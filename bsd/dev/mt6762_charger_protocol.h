/* PSC5425E Rev06.5, manufacturer register contract. No charge-enable API. */
#ifndef MT6762_CHARGER_PROTOCOL_H
#define MT6762_CHARGER_PROTOCOL_H
#include <stdint.h>
struct mt6762_psc_io {
    void *context;
    int (*read)(void *,uint8_t,uint8_t *);
    int (*write)(void *,uint8_t,uint8_t);
};
/* Caller must hold exclusive control ownership across this entire operation.
 * Success means CE was read back disabled, not that an electrical fallback
 * exists. Bus failure leaves control safety unknown. No guessed reset. */
static inline int
mt6762_psc_disable_owned(const struct mt6762_psc_io *io,int owned,uint8_t *control)
{
    uint8_t id,before,after;
    int e;
    if(!io || !io->read || !io->write || !control || !owned)return -1;
    if((e=io->read(io->context,3,&id)))return e;
    if(id!=0xf0)return -2;
    if((e=io->read(io->context,1,&before)))return e;
    /* OPA_MODE belongs to OTG, whose physical routing is not established. */
    if(before&1)return -3;
    if(!(before&4) && (e=io->write(io->context,1,before|4)))return e;
    if((e=io->read(io->context,1,&after)))return e;
    if(after!=(uint8_t)(before|4))return -4;
    *control=after;
    return 0;
}
/* Decoders expose nominal chip values, not calibrated board limits. ICE and
 * ADD20MV must be read rather than assumed. Rsense is in micro-ohms and must
 * be supplied from independent board evidence, never selected by this code. */
static inline int mt6762_psc_voltage_uv(uint8_t reg2,uint8_t reg5,uint32_t *uv)
{
    unsigned code=reg2>>2;
    uint32_t v;
    if(!uv || code==63)return -1;
    v=code<2?4100000:code<36?4200000:code<45?4350000:4400000;
    *uv=v+((reg5&0x80)?20000:0);return 0;
}
static inline int mt6762_psc_input_ua(uint8_t reg1,uint32_t *ua)
{
    static const uint32_t current[]={150000,500000,800000};
    unsigned code=reg1>>6;
    if(!ua || code==3)return -1; /* No finite limit; never invent a number. */
    *ua=current[code];return 0;
}
static inline int
mt6762_psc_current_ua(uint8_t reg4,uint8_t reg51,uint32_t rsense_uohm,uint32_t *ua)
{
    static const uint32_t sense_uv[2][8]={{32800,39300,52400,59000,72100,78700,91800,98300},
                                        {26700,33300,40000,46700,53300,60000,66700,86700}};
    uint64_t value;
    if(!ua || !rsense_uohm)return -1;
    value=(uint64_t)sense_uv[reg51&1][(reg4>>4)&7]*1000000/rsense_uohm;
    if(value>UINT32_MAX)return -1;
    *ua=(uint32_t)value;return 0;
}
static inline int mt6762_psc_termination_ua(uint8_t reg4,uint32_t rsense_uohm,uint32_t *ua)
{
    static const uint32_t sense_uv[]={2500,3800,5000,6300,7500,8800,10000,11300};
    uint64_t value;
    if(!ua || !rsense_uohm)return -1;
    value=(uint64_t)sense_uv[reg4&7]*1000000/rsense_uohm;
    if(value>UINT32_MAX)return -1;
    *ua=(uint32_t)value;return 0;
}
#endif
