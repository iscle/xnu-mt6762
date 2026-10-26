/* SPDX-License-Identifier: MIT */
#ifndef MT6762_TRIAL_DEADLINE_H
#define MT6762_TRIAL_DEADLINE_H
#include <stdint.h>
#include <stddef.h>

/* Decimal-only boot argument. Missing/invalid input leaves the trial disabled;
 * never accept truncation/wrapping of a large number as a short deadline. */
static inline int mtk_trial_parse(const char *s, size_t capacity, unsigned *seconds)
{
    unsigned n=0;
    *seconds=0;
    if (!s || !capacity || !s[0]) return 0;
    for (size_t i=0;i<capacity;i++) {
        unsigned char c=(unsigned char)s[i];
        if (!c) {
            if (n && (n<60 || n>1800)) return 0;
            *seconds=n;return 1;
        }
        if (c<'0' || c>'9' || n>1800) return 0;
        n=n*10+(c-'0');
    }
    return 0;
}

struct mtk_trial_deadline {
    uint64_t first_ns;
    unsigned seconds,started,expired;
};
/* Host retrieval must bind this symbol to the selected kernel/trial manifest.
 * This is an ordinary diagnostic record, not a unique boot attestation.
 * state:0 disabled,1 armed,2 expired,3 cache-clean operations completed. */
struct mtk_trial_record {
    uint64_t magic;
    uint32_t version,state,seconds,attempts,flags,reserved0;
    uint64_t first_feed_ns,last_feed_ns,expired_ns;
    uint32_t log_length_before,log_length_after;
    uint32_t mode,length,status,nonrst,nonrst2,req_mode,req_irq;
    uint32_t reserved[9];
};
_Static_assert(sizeof(struct mtk_trial_record)==128,"trial record ABI");
enum { MTK_TRIAL_CONCURRENT_LOG=1, MTK_TRIAL_LOG_LENGTH_INVALID=2 };
static inline void mtk_trial_fed(struct mtk_trial_deadline *t,uint64_t now_ns)
{
    if (!t->started) {t->first_ns=now_ns;t->started=1;}
}
/* Called after the existing profile/scheduling checks and before a refresh.
 * Subtraction avoids overflow near UINT64_MAX. Backwards clocks remain the
 * existing worker's scheduling-failure case, not fabricated deadline expiry. */
static inline int mtk_trial_expired(struct mtk_trial_deadline *t,uint64_t now_ns)
{
    if (t->expired) return 1;
    if (t->seconds && t->started && now_ns>=t->first_ns &&
        now_ns-t->first_ns>=(uint64_t)t->seconds*UINT64_C(1000000000))
        t->expired=1;
    return (int)t->expired;
}

/* Fixed-allocation cache maintenance, independent of any mutable log length.
 * clean receives aligned cache-line addresses, not byte loads/stores. */
static inline int mtk_trial_clean_range(uintptr_t base,size_t bytes,
    void (*clean)(uintptr_t,void *),void *context)
{
    if (!bytes) return 0;
    if (!clean || bytes-1>UINTPTR_MAX-base) return -1;
    uintptr_t last=(base+bytes-1)&~(uintptr_t)63;
    for (uintptr_t p=base&~(uintptr_t)63;;p+=64) {
        clean(p,context);
        if (p==last) break;
    }
    return 0;
}
#endif
