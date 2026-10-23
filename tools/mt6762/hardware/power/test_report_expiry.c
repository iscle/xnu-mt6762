/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdio.h>
#include "report_expiry.h"
/* Model only publication decisions; actual IOKit field-removal behavior is
 * checked by the read-only guest probe, not reproduced in this host test. */
int main(void)
{
    struct mt6762_report_expiry s = {0};
    assert(mt6762_report_receive(&s, 0, 2000, 1, 0x4f, 2000) == MT6762_REPORT_CLEAR);
    assert(!s.active);
    assert(mt6762_report_receive(&s, 1000, 3000, 1000, 0x4f, 2000) == MT6762_REPORT_APPLY);
    assert(mt6762_report_expire(&s, 2999) == MT6762_REPORT_IGNORE);
    /* A queued timer for the old3000 deadline runs after a new sample. */
    assert(mt6762_report_receive(&s, 2000, 4000, 2001, 0x4f, 2000) == MT6762_REPORT_APPLY);
    assert(mt6762_report_expire(&s, 3000) == MT6762_REPORT_IGNORE && s.active);
    /* Expired old arrivals and duplicate acquisition cannot erase it. */
    assert(mt6762_report_receive(&s, 900, 2900, 3001, 0x4f, 2000) == MT6762_REPORT_IGNORE);
    assert(mt6762_report_receive(&s, 2000, 2001, 3001, 0, 2000) == MT6762_REPORT_IGNORE);
    assert(s.active && s.expires == 4000);
    assert(mt6762_report_expire(&s, 4000) == MT6762_REPORT_CLEAR && !s.active);
    assert(mt6762_report_expire(&s, 4001) == MT6762_REPORT_IGNORE);
    /* The producer stopped: timer alone clears. A later fresh report recovers. */
    assert(mt6762_report_receive(&s, 5000, 7000, 5000, 0x4f, 2000) == MT6762_REPORT_APPLY);
    assert(mt6762_report_expire(&s, 7000) == MT6762_REPORT_CLEAR);
    assert(mt6762_report_receive(&s, 8000, 10000, 8000, 0x4f, 2000) == MT6762_REPORT_APPLY);
    /* Newer acquisition may carry a shorter earliest source deadline. */
    assert(mt6762_report_receive(&s, 8500, 9000, 8500, 0x5f, 2000) == MT6762_REPORT_APPLY);
    assert(s.last_acquired == 8500 && s.expires == 9000);
    assert(mt6762_report_expire(&s, 9000) == MT6762_REPORT_CLEAR);
    /* A slow acquisition cannot gain lifetime when finally published. */
    assert(mt6762_report_receive(&s, 9500, 11500, 11500, 0x4f, 2000) == MT6762_REPORT_CLEAR);
    assert(!s.active);
    assert(mt6762_report_receive(&s, 12000, 14000, 12000, 0x4f, 2000) == MT6762_REPORT_APPLY);
    assert(mt6762_report_receive(&s, 12500, 14500, 12500, 0, 2000) == MT6762_REPORT_CLEAR);
    assert(!s.active); /* explicit invalid reading immediately removes prior data */
    assert(mt6762_report_receive(&s, 13000, 0, 13000, 0x4f, 2000) == MT6762_REPORT_CLEAR);
    assert(mt6762_report_receive(&s, 14001, 15000, 14000, 0x4f, 2000) == MT6762_REPORT_CLEAR);
    assert(mt6762_report_receive(&s, 14000, 16001, 14000, 0x4f, 2000) == MT6762_REPORT_CLEAR);
    /* A timer delayed past a rejected older report still clears expired data. */
    assert(mt6762_report_receive(&s, 15000, 17000, 15000, 0x4f, 2000) == MT6762_REPORT_APPLY);
    assert(mt6762_report_receive(&s, 14900, 16900, 17001, 0x4f, 2000) == MT6762_REPORT_CLEAR);
    mt6762_report_stop(&s);
    assert(!s.active && s.stopped);
    assert(mt6762_report_receive(&s, 18000, 20000, 18000, 0x4f, 2000) == MT6762_REPORT_IGNORE);
    assert(mt6762_report_expire(&s, UINT64_MAX) == MT6762_REPORT_IGNORE);
    /* Subtraction-based checks do not wrap at the absolute-time limit. */
    struct mt6762_report_expiry edge = {0};
    assert(mt6762_report_receive(&edge, UINT64_MAX - 1000, UINT64_MAX,
        UINT64_MAX - 500, 1, 2000) == MT6762_REPORT_APPLY);
    assert(mt6762_report_expire(&edge, UINT64_MAX) == MT6762_REPORT_CLEAR);
    puts("Native report acquisition-age/expiry/order/stop tests passed");
    return 0;
}
