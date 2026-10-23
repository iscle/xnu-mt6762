/* Recovered MT6357 NTC/BIF request protocol. No ADC reset or trim writes.
 * Exclusive ADC and BATON/TDET ownership are caller prerequisites. */
#ifndef MT6762_BIF_PROTOCOL_H
#define MT6762_BIF_PROTOCOL_H
#include <stdint.h>
struct mt6762_battery_adc_io {
    void *context;
    int (*read)(void *,uint16_t,uint16_t *);
    int (*write)(void *,uint16_t,uint16_t);
    void (*delay_us)(void *,unsigned);
};
/* Returns a raw sample only after observing post-request READY low then high.
 * A very fast conversion whose transition was missed is rejected, never guessed.
 * -1 arguments, -2 I/O, -3 timeout, -4 rail/reserved data, -5 no generation. */
static inline int mt6762_battery_adc_fresh(const struct mt6762_battery_adc_io *io,
                                          unsigned channel,uint16_t *out)
{
    uint16_t address,word,mask;
    unsigned wait_us;
    if(!io || !io->read || !io->write || !io->delay_us || !out)return -1;
    switch(channel) {
    case 1: address=0x108a;mask=32767;wait_us=1280;break;
    case 3: address=0x108e;mask=4095;wait_us=80;break;
    case 11:address=0x109e;mask=4095;wait_us=80;break;
    default:return -1;
    }
    if(io->write(io->context,0x110e,(uint16_t)(1u<<channel)) ||
       io->read(io->context,address,&word))return -2;
    if(word&0x8000)return -5;
    io->delay_us(io->context,wait_us);
    for(unsigned i=0;i<160;i++) {
        if(io->read(io->context,address,&word))return -2;
        if(word&0x8000) {
            if((word&~(0x8000u|mask)) || !(word&mask) || (word&mask)==mask)return -4;
            *out=word&mask;return 0;
        }
        io->delay_us(io->context,200);
    }
    return -3;
}
struct mt6762_bif_pair {uint16_t ntc_raw,bif_raw;};
struct mt6762_bif_transport {
    struct mt6762_battery_adc_io io;
    uint16_t expected_tdet; /* Actual verified handoff word, never a default. */
    unsigned fault,restoration_unknown;
};
/* Restore only if readback still matches the phase owned by this transaction.
 * An unexpected word is ownership loss; do not overwrite somebody else's state.
 * Original already restored is known safe for this bit, but remains an error. */
static inline int mt6762_bif_restore(struct mt6762_bif_transport *t,
                                    uint16_t original,uint16_t temporary)
{
    uint16_t word;
    if(t->io.read(t->io.context,0x1236,&word))goto unknown;
    if(word==original)return temporary==original?0:-6;
    if(word!=temporary)goto unknown;
    if(t->io.write(t->io.context,0x1236,original) ||
       t->io.read(t->io.context,0x1236,&word) || word!=original)goto unknown;
    return 0;
unknown:
    t->restoration_unknown=1;return -7;
}
/* Only success commits both fresh samples. Any failed transaction is sticky.
 * On conversion failure, exact restoration is still attempted while the bus is
 * usable. A failed restore is explicitly unknown; no independent fallback is
 * invented here. Native admission must establish that fallback beforehand. */
static inline int mt6762_bif_capture(struct mt6762_bif_transport *t,
                                    struct mt6762_bif_pair *out)
{
    struct mt6762_bif_pair pair;
    uint16_t original,temporary,word;
    int e,changed=0;
    if(!t || !out || !t->io.read || !t->io.write || !t->io.delay_us || t->fault)return -1;
    if(t->io.read(t->io.context,0x1236,&original)) {e=-2;goto failed;}
    if(original!=t->expected_tdet) {e=-6;goto failed;}
    e=mt6762_battery_adc_fresh(&t->io,3,&pair.ntc_raw);
    if(e)goto failed;
    if(t->io.read(t->io.context,0x1236,&word)) {e=-2;goto failed;}
    if(word!=original) {e=-6;goto failed;}
    temporary=original&~2u;
    if(temporary!=original) {
        changed=1; /* A failed write can still have reached the PMIC. */
        if(t->io.write(t->io.context,0x1236,temporary)) {e=-2;goto restore;}
        if(t->io.read(t->io.context,0x1236,&word)) {e=-2;goto restore;}
        if(word!=temporary) {e=-6;goto restore;}
    }
    e=mt6762_battery_adc_fresh(&t->io,11,&pair.bif_raw);
    /* Even originally-clear TDET needs a final unchanged-state observation. */
restore:
    if(changed) {
        int restoration=mt6762_bif_restore(t,original,temporary);
        if(restoration)e=restoration;
    } else {
        if(t->io.read(t->io.context,0x1236,&word) || word!=original) {
            t->restoration_unknown=1;e=-7;
        }
    }
    if(e)goto failed;
    *out=pair;return 0;
failed:
    t->fault=1;return e;
}
/* Native-only retry admission for a missed READY-low measurement. Requires an
 * already-clear TDET word, independently rechecked configuration and another
 * exact TDET readback. Never recovers I/O, timeout, ownership or restore faults.
 * Returns1 if admitted,0 if ineligible,negative on failed final readback. */
static inline int mt6762_bif_retry_generation(struct mt6762_bif_transport *t,
                                              int error,unsigned config_verified)
{
    uint16_t observed;
    if(!t || !t->io.read || error!=-5 || config_verified!=1 ||
       (t->expected_tdet&2) || t->restoration_unknown || t->fault!=1)return 0;
    if(t->io.read(t->io.context,0x1236,&observed))return -2;
    if(observed!=t->expected_tdet)return -6;
    t->fault=0;return 1;
}
#endif
