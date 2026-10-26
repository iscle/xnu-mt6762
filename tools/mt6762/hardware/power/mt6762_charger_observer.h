/* SPDX-License-Identifier: MIT -- repeated, read-only PSC telemetry policy.
 * Consumes attempts under the caller's I2C mutex; never permits charger writes.
 * Times are monotonic microseconds. Transport failure must latch faulted.
 */
#ifndef MT6762_CHARGER_OBSERVER_H
#define MT6762_CHARGER_OBSERVER_H
#include <stddef.h>
#include <stdint.h>
struct mt6762_charger_observer {
    uint64_t began_us, last_us;
    unsigned index, started, faulted;
};
static inline int mt6762_charger_observer_request(
    struct mt6762_charger_observer *s, uint64_t now_us, unsigned address,
    const void *tx, size_t nt, size_t nr)
{
    static const uint8_t regs[3]={3,1,0};
    if(!s || s->faulted || s->index>2 || address!=0x6a || !tx || nt!=1 || nr!=1 ||
       *(const uint8_t *)tx!=regs[s->index])return 0;
    if(s->started && (now_us<s->last_us ||
       (s->index && now_us-s->began_us>100000))) {
        s->faulted=1;return 0;
    }
    /* At most two samples/second, each three reads within100ms. Polling at
     * roughly1Hz leaves scheduling margin without allowing unbounded bursts. */
    if(!s->index) {
        if(s->started && now_us-s->began_us<500000)return 0;
        s->began_us=now_us;s->started=1;
    }
    s->last_us=now_us;s->index=(s->index+1)%3;
    return 1;
}
static inline int mt6762_charger_observer_complete(
    struct mt6762_charger_observer *s,uint64_t now_us,int error)
{
    if(!s)return 0;
    if(s->faulted || !s->started || error || now_us<s->last_us ||
       now_us-s->began_us>100000) {s->faulted=1;return 0;}
    s->last_us=now_us;return 1;
}
#endif
