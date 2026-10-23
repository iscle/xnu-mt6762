/* SPDX-License-Identifier: MIT
 * Internal battery observation age/order state. Caller serializes all access.
 * Times share mach_absolute_time units; no Apple ABI or fabricated readings. */
#ifndef MT6762_REPORT_EXPIRY_H
#define MT6762_REPORT_EXPIRY_H
#include <stdint.h>
enum { MT6762_REPORT_IGNORE = -1, MT6762_REPORT_CLEAR = 0, MT6762_REPORT_APPLY = 1 };
struct mt6762_report_expiry {
    uint64_t last_acquired, expires;
    unsigned seen, active, stopped;
};
static inline int mt6762_report_fresh(uint64_t acquired, uint64_t expires,
    uint64_t now, uint64_t maximum_age)
{
    return acquired && acquired <= now && expires > acquired && expires > now &&
        maximum_age && expires - acquired <= maximum_age;
}
static inline int mt6762_report_expire(struct mt6762_report_expiry *s, uint64_t now)
{
    if (!s->stopped && s->active && now >= s->expires) {
        s->active = 0;
        return MT6762_REPORT_CLEAR;
    }
    return MT6762_REPORT_IGNORE;
}
static inline int mt6762_report_receive(struct mt6762_report_expiry *s,
    uint64_t acquired, uint64_t expires, uint64_t now, unsigned valid, uint64_t maximum_age)
{
    if (s->stopped) return MT6762_REPORT_IGNORE;
    /* An old callback/report cannot erase a newer, still-fresh observation.
     * Acquisition orders reports; a newly included field can shorten expiry. */
    if (s->seen && acquired <= s->last_acquired) return mt6762_report_expire(s, now);
    if (acquired <= now) {
        s->last_acquired = acquired;
        s->seen = 1;
    }
    if (!valid || !mt6762_report_fresh(acquired, expires, now, maximum_age)) {
        s->active = 0;
        return MT6762_REPORT_CLEAR;
    }
    s->expires = expires;
    s->active = 1;
    return MT6762_REPORT_APPLY;
}
static inline void mt6762_report_stop(struct mt6762_report_expiry *s)
{
    s->stopped = 1;
    s->active = 0;
}
#endif
