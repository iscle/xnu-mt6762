/* SPDX-License-Identifier: MIT
 * Bounded reuse of inherited static pad/rail observations, not ownership.
 * The caller serializes all access and retains the loader ownership contract.
 * Clock/IRQ checks still surround EVERY admission; controller/DMA/card checks
 * remain in mt6762_msdc_protocol.h. This policy cannot detect a secure-world
 * pad/rail change until the next full pass. See ADMISSION-PERFORMANCE.rst.
 */
#ifndef MT6762_MSDC_ADMISSION_H
#define MT6762_MSDC_ADMISSION_H
#include <stdint.h>

#define MT6762_MSDC_STATIC_US 1000u
#define MT6762_MSDC_STATIC_SECTORS 256u

struct mt6762_msdc_admission {
    uint64_t observed_start, last_time;
    uint64_t calls, full, reused, full_us, full_max_us, slow_full;
    uint64_t failures, clock_reversals;
    unsigned valid, have_time, sectors;
};
struct mt6762_msdc_admission_io {
    void *context;
    uint64_t (*time_us)(void *);
    int (*before)(void *); /* zero only if ownership/IRQ/clocks still hold */
    int (*observe_static)(void *); /* pads/tuning and twice-read PMIC words */
    int (*after)(void *); /* zero only if clocks/IRQ still hold */
};
static inline void mt6762_msdc_admission_invalidate(struct mt6762_msdc_admission *s)
{s->valid=0;s->sectors=0;}

static inline int mt6762_msdc_admission_time(struct mt6762_msdc_admission *s,
    const struct mt6762_msdc_admission_io *io,uint64_t *now)
{
    *now=io->time_us(io->context);
    if(s->have_time && *now<s->last_time) {
        s->clock_reversals++;
        return -1;
    }
    s->have_time=1;s->last_time=*now;
    return 0;
}

static inline int mt6762_msdc_admission_check(struct mt6762_msdc_admission *s,
    const struct mt6762_msdc_admission_io *io)
{
    uint64_t start=0,now=0;
    int fresh=0,error;
    s->calls++;
    if(mt6762_msdc_admission_time(s,io,&start))goto failed;
    if(io->before(io->context))goto failed;
    /* Scheduling during the cheap checks must not extend the reuse window. */
    if(mt6762_msdc_admission_time(s,io,&now))goto failed;
    if(!s->valid || now-s->observed_start>=MT6762_MSDC_STATIC_US ||
       s->sectors>=MT6762_MSDC_STATIC_SECTORS) {
        mt6762_msdc_admission_invalidate(s);
        s->full++;fresh=1;
        error=io->observe_static(io->context);
        if(error)goto finished;
    }
    error=io->after(io->context);
finished:
    if(mt6762_msdc_admission_time(s,io,&now))goto failed;
    if(fresh) {
        uint64_t elapsed=now-start;
        s->full_us+=elapsed;
        if(elapsed>s->full_max_us)s->full_max_us=elapsed;
        if(elapsed>=MT6762_MSDC_STATIC_US)s->slow_full++;
        /* A slow successful observation permits this one admission, but
         * never grants a fresh window starting at its completion. */
        if(!error && elapsed<MT6762_MSDC_STATIC_US) {
            s->observed_start=start;s->valid=1;
        }
    } else if(!error) {
        s->reused++;
        if(now-s->observed_start>=MT6762_MSDC_STATIC_US)
            mt6762_msdc_admission_invalidate(s);
    }
    if(error)goto failed;
    return 0;
failed:
    s->failures++;
    mt6762_msdc_admission_invalidate(s);
    return -1;
}

static inline void mt6762_msdc_admission_sector_done(struct mt6762_msdc_admission *s)
{
    if(s->valid && ++s->sectors>=MT6762_MSDC_STATIC_SECTORS)
        mt6762_msdc_admission_invalidate(s);
}
#endif
