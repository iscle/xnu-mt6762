/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdio.h>
#include "apple_backlight_core.h"
int main(void)
{
    uint64_t us = 123;
    assert(!mt6762_backlight_request(0, 0, &us) && us == 0);
    assert(!mt6762_backlight_request(1023, 65536, &us) && us == 1000000);
    assert(!mt6762_backlight_request(512, 32768, &us) && us == 500000);
    assert(!mt6762_backlight_request(1, 1, &us) && us == 15);
    assert(!mt6762_backlight_request(1, INT32_MAX, &us) && us == 32767999984ULL);
    assert(mt6762_backlight_request(1024, 0, &us) < 0);
    assert(mt6762_backlight_request(UINT32_MAX, 0, &us) < 0);
    assert(mt6762_backlight_request(UINT64_MAX, 0, &us) < 0);
    assert(mt6762_backlight_request(0, UINT32_MAX, &us) < 0);
    assert(mt6762_backlight_request(0, UINT64_MAX, &us) < 0);
    assert(mt6762_backlight_request(0, 0, NULL) < 0);
    assert(mt6762_backlight_step(0, 1023, 0, 1000000) == 0);
    assert(mt6762_backlight_step(0, 1023, 500000, 1000000) == 511);
    assert(mt6762_backlight_step(1023, 0, 500000, 1000000) == 512);
    assert(mt6762_backlight_step(1023, 0, 1000000, 1000000) == 0);
    assert(mt6762_backlight_step(0, 1023, UINT64_MAX, 1000000) == 1023);
    assert(mt6762_backlight_step(512, 20, 0, 0) == 20);
    /* Retarget from the last confirmed hardware level, not the old target. */
    unsigned midway = mt6762_backlight_step(0, 1000, 250000, 1000000);
    assert(midway == 250 && mt6762_backlight_step(midway, 0, 500000, 1000000) == 125);
    unsigned previous = 0;
    for (unsigned i = 0; i <= 1000000; i += 1000) {
        unsigned now = mt6762_backlight_step(0, 1023, i, 1000000);
        assert(now >= previous && now <= 1023); previous = now;
    }
    puts("Apple legacy integer brightness/fixed16.16 fade tests passed");
    return 0;
}
