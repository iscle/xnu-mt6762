/* SPDX-License-Identifier: MIT
 * MT6762 inherited MSDC0 read-only PIO. Serialized caller, exclusive ownership.
 * Evidence: tools/mt6762/hardware/storage. Never resets, tunes, switches card
 * partitions/modes, launches DMA, or emits a storage-write command. */
#ifndef MT6762_MSDC_PROTOCOL_H
#define MT6762_MSDC_PROTOCOL_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "mt6762_msdc_clock.h"

enum {
    MT6762_MSDC_ARGUMENT=-1, MT6762_MSDC_OWNERSHIP=-2,
    MT6762_MSDC_STATE=-3, MT6762_MSDC_TIMEOUT=-4,
    MT6762_MSDC_COMMAND=-5, MT6762_MSDC_DATA=-6,
    MT6762_MSDC_CARD=-7, MT6762_MSDC_ACK=-8, MT6762_MSDC_FAULTED=-9
};
struct mt6762_msdc_io {
    void *ctx;
    /* Must independently validate exclusive handoff, masked GIC, clocks,
     * power, pads and preserved tuning. Register-idle alone is insufficient. */
    int (*admit)(void *);
    uint32_t (*read32)(void *,uint32_t);
    /* Callback includes the device write-completion barrier (stock dsb sy). */
    void (*write32)(void *,uint32_t,uint32_t);
    uint64_t (*time_us)(void *);
    void (*delay_us)(void *,uint32_t);
};
struct mt6762_msdc_config {
    uint64_t sector_count;
    uint32_t rca, expected_cfg, expected_sdc_cfg, timeout_us, card_clock_hz;
};
struct mt6762_msdc {
    struct mt6762_msdc_io io;
    struct mt6762_msdc_config config;
    unsigned initialized, faulted;
    /* RAM diagnostics; never read additional MMIO after a terminal failure. */
    uint32_t last_command, last_argument, data_bytes, last_irq;
    unsigned wait_phase; /* 1 command response, 2 FIFO/completion */
    uint64_t stalled_us;
};
static inline int mt6762_msdc_fail(struct mt6762_msdc *s,int error)
{
    s->faulted=1;
    return error;
}
static inline uint32_t mt6762_msdc_r(struct mt6762_msdc *s,uint32_t reg)
{
    return s->io.read32(s->io.ctx,reg);
}
static inline void mt6762_msdc_w(struct mt6762_msdc *s,uint32_t reg,uint32_t value)
{
    s->io.write32(s->io.ctx,reg,value);
}
static inline int mt6762_msdc_quiet(struct mt6762_msdc *s)
{
    if(s->io.admit(s->io.ctx))return MT6762_MSDC_OWNERSHIP;
    if(mt6762_msdc_r(s,0)!=s->config.expected_cfg ||
       mt6762_msdc_r(s,0x30)!=s->config.expected_sdc_cfg ||
       mt6762_msdc_r(s,0x10) || mt6762_msdc_r(s,0x0c) ||
       (mt6762_msdc_r(s,0x3c)&3) || (mt6762_msdc_r(s,0x9c)&1) ||
       (mt6762_msdc_r(s,0x14)&0x80ff00ffu) ||
       (mt6762_msdc_r(s,0x204)&1) || (mt6762_msdc_r(s,0x23c)&3) ||
       (mt6762_msdc_r(s,0x670)&7)!=4)return MT6762_MSDC_STATE;
    return 0;
}
static inline int mt6762_msdc_wait_step(struct mt6762_msdc *s,uint64_t start,unsigned *polls)
{
    uint64_t now=s->io.time_us(s->io.ctx);
    s->stalled_us=now>=start?now-start:UINT64_MAX;
    if(now<start || now-start>=s->config.timeout_us ||
       (*polls)++>=s->config.timeout_us)return MT6762_MSDC_TIMEOUT;
    s->io.delay_us(s->io.ctx,1);
    return 0;
}
static inline int mt6762_msdc_ack(struct mt6762_msdc *s,uint32_t bits)
{
    if(bits)mt6762_msdc_w(s,0x0c,bits);
    return (mt6762_msdc_r(s,0x0c)&bits)?MT6762_MSDC_ACK:0;
}
static inline int mt6762_msdc_command(struct mt6762_msdc *s,uint32_t command,
    uint32_t arg,uint32_t *r1)
{
    if((command!=0x8d && command!=0x02000888 && command!=0x02000891) ||
       (command==0x02000888 && arg) ||
       (command==0x8d && arg!=(s->config.rca<<16)))return MT6762_MSDC_ARGUMENT;
    unsigned polls=0;int expired=0;
    int error=mt6762_msdc_quiet(s);
    if(error)return error;
    mt6762_msdc_w(s,0x38,arg);
    mt6762_msdc_w(s,0x34,command);
    s->last_command=command;s->last_argument=arg;s->wait_phase=1;
    s->data_bytes=0;s->stalled_us=0;
    uint64_t start=s->io.time_us(s->io.ctx);
    for(;;) {
        uint32_t irq=mt6762_msdc_r(s,0x0c), owned=irq&0x700;
        s->last_irq=irq;
        if(owned) {
            /* Error wins over simultaneous completion. No partial success. */
            if(owned&0x600)return MT6762_MSDC_COMMAND;
            *r1=mt6762_msdc_r(s,0x40);
            error=mt6762_msdc_ack(s,owned);
            if(error)return error;
            /* eMMC R1 bit6 is EXCEPTION_EVENT, an EXT_CSD/BKOPS notification,
             * not a failed command. Keep switch/error/locked-card checks.
             * This read-only transport does not start background operations. */
            if(*r1&0xffffe080u)return MT6762_MSDC_CARD;
            return 0;
        }
        /* A scheduler gap can occur between the status read and clock read.
         * Re-sample once at expiry; never reject a completed command using
         * a pre-descheduling not-ready value. Hardware error still wins. */
        if(expired)return expired;
        expired=mt6762_msdc_wait_step(s,start,&polls);
        if(expired && s->stalled_us==UINT64_MAX)return expired;
    }
}
static inline int mt6762_msdc_status(struct mt6762_msdc *s)
{
    uint32_t r1=0;
    int error=mt6762_msdc_command(s,0x8d,s->config.rca<<16,&r1);
    if(error)return error;
    if((r1&0x1f00)!=0x900)return MT6762_MSDC_CARD;
    return mt6762_msdc_quiet(s);
}
static inline int mt6762_msdc_data512(struct mt6762_msdc *s,uint32_t opcode,
    uint32_t arg,uint8_t data[512])
{
    if((opcode!=8 && opcode!=17) ||
       (opcode==17 && arg>=s->config.sector_count))return MT6762_MSDC_ARGUMENT;
    uint32_t r1=0;
    unsigned have=0,polls=0;int expired=0;
    int error=mt6762_msdc_quiet(s);
    if(error)return error;
    mt6762_msdc_w(s,0x50,1);
    if(mt6762_msdc_r(s,0x50)!=1)return MT6762_MSDC_STATE;
    error=mt6762_msdc_command(s,0x02000880u|opcode,arg,&r1);
    if(error)return error;
    uint64_t start=s->io.time_us(s->io.ctx);
    s->wait_phase=2;
    for(;;) {
        uint32_t irq=mt6762_msdc_r(s,0x0c),fifo=mt6762_msdc_r(s,0x14)&0xff;
        s->last_irq=irq;
        if(irq&0xc000)return MT6762_MSDC_DATA;
        if(fifo>512-have)return MT6762_MSDC_DATA;
        if(fifo>=64 && have<512) {
            /* Exact stock PIO path drains sixteen32-bit words per64bytes. */
            for(unsigned i=0;i<16;i++) {
                uint32_t word=mt6762_msdc_r(s,0x1c);
                for(unsigned j=0;j<4;j++)data[have++]=(uint8_t)(word>>(j*8));
            }
            s->data_bytes=have;
            /* Bound stalls, not CPU scheduling delays while data is ready.
             * There are only eight chunks. Re-read IRQ before accepting the
             * final completion so a concurrent data error still wins. */
            uint64_t now=s->io.time_us(s->io.ctx);
            if(now<start)return MT6762_MSDC_TIMEOUT;
            start=now;polls=0;s->stalled_us=0;expired=0;
            continue;
        }
        if(have==512 && (irq&0x1000)) {
            error=mt6762_msdc_ack(s,0x1000);
            if(error)return error;
            return mt6762_msdc_quiet(s);
        }
        if(expired)return expired;
        expired=mt6762_msdc_wait_step(s,start,&polls);
        if(expired && s->stalled_us==UINT64_MAX)return expired;
    }
}
static inline int mt6762_msdc_init(struct mt6762_msdc *s,
    const struct mt6762_msdc_io *io,const struct mt6762_msdc_config *config)
{
    uint8_t ext[512];
    int error;
    if(!s || !io || !config)return MT6762_MSDC_ARGUMENT;
    /* Caller supplies a zero-initialized object once. A fault is terminal;
     * init is not an implicit recovery/reset of inherited ownership. */
    if(s->initialized || s->faulted)return MT6762_MSDC_FAULTED;
    memset(s,0,sizeof(*s));
    if(!io->admit || !io->read32 || !io->write32 || !io->time_us || !io->delay_us ||
       !config->sector_count || config->sector_count>UINT32_MAX ||
       !config->rca || config->rca>0xffff || !config->timeout_us || config->timeout_us>1000000 ||
       !config->card_clock_hz || config->card_clock_hz>200000000 ||
       (config->expected_cfg&0x8d)!=0x89 ||
       (config->expected_sdc_cfg&0x30000)!=0x20000)return MT6762_MSDC_ARGUMENT;
    s->io=*io;s->config=*config;
    if((error=mt6762_msdc_status(s)) ||
       (error=mt6762_msdc_data512(s,8,0,ext)) ||
       (error=mt6762_msdc_status(s)))return mt6762_msdc_fail(s,error);
    uint32_t sectors=(uint32_t)ext[212]|((uint32_t)ext[213]<<8)|
        ((uint32_t)ext[214]<<16)|((uint32_t)ext[215]<<24);
    unsigned mode=(config->expected_cfg>>20)&3, timing=ext[185]&15;
    /* BUS_WIDTH[183] has no defined readback. The inherited host8-bit mode
     * was checked before commands and throughout the CRC-checked EXT_CSD
     * transfer. Validate only readable card state against that host mode. */
    if(sectors!=config->sector_count || (ext[179]&7) || ext[15] ||
       !mt6762_msdc_card_rate_ok(timing,mode,ext[196],config->card_clock_hz))
        return mt6762_msdc_fail(s,MT6762_MSDC_CARD);
    s->initialized=1;
    return 0;
}
static inline int mt6762_msdc_read512(struct mt6762_msdc *s,uint64_t lba,void *out512)
{
    uint8_t data[512];
    int error;
    if(!s || !out512)return MT6762_MSDC_ARGUMENT;
    if(s->faulted)return MT6762_MSDC_FAULTED;
    if(!s->initialized || lba>=s->config.sector_count || lba>UINT32_MAX)return MT6762_MSDC_ARGUMENT;
    if((error=mt6762_msdc_status(s)) ||
       (error=mt6762_msdc_data512(s,17,(uint32_t)lba,data)) ||
       (error=mt6762_msdc_status(s)))return mt6762_msdc_fail(s,error);
    memcpy(out512,data,512);
    return 0;
}
#endif
