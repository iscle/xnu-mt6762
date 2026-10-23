/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdio.h>
#include "apple_backlight_core.h"
int main(void)
{
    /* CFNumber SInt8/16/32/64 are valid integer encodings. Even exact integral
     * floating values must be rejected by type, before an unsigned conversion
     * could conceal fractions, NaN or a negative value. */
    assert(mt6762_backlight_integer_type(8));
    assert(mt6762_backlight_integer_type(16));
    assert(mt6762_backlight_integer_type(32));
    assert(mt6762_backlight_integer_type(64));
    assert(!mt6762_backlight_integer_type(31));
    assert(!mt6762_backlight_integer_type(63));
    assert(!mt6762_backlight_integer_type(0));
    assert(!mt6762_backlight_integer_type(65));
    assert(!mt6762_backlight_integer_type(UINT32_MAX));
    /* Off in mid-fade saves confirmed300, never the unconfirmed900 target.
     * A later authenticated off-screen request supersedes that restore level;
     * repeated off must preserve it. No target is an actual-duty sample. */
    struct mt6762_backlight_lifecycle lifecycle = {MT6762_BACKLIGHT_ACTIVE, 512, 0};
    assert(mt6762_backlight_desire(&lifecycle, 900, 1000000) == 0);
    mt6762_backlight_blank_confirmed(&lifecycle, 300);
    assert(lifecycle.mode == MT6762_BACKLIGHT_BLANKED && lifecycle.desired == 300 && !lifecycle.fade_us);
    assert(mt6762_backlight_desire(&lifecycle, 256, 500000) == 1);
    assert(mt6762_backlight_desire(&lifecycle, 768, 1000000) == 1);
    mt6762_backlight_blank_confirmed(&lifecycle, 0);
    assert(lifecycle.desired == 768 && lifecycle.fade_us == 1000000);
    assert(mt6762_backlight_desire(&lifecycle, 1024, 0) == -1);
    assert(lifecycle.desired == 768);
    /* Wake uses the pending target/fade from actual zero, not stale300. */
    assert(mt6762_backlight_step(0, lifecycle.desired, 500000, lifecycle.fade_us) == 384);
    lifecycle.mode = MT6762_BACKLIGHT_ACTIVE;
    mt6762_backlight_blank_confirmed(&lifecycle, 384);
    assert(lifecycle.desired == 384 && !lifecycle.fade_us);
    lifecycle.mode = MT6762_BACKLIGHT_STOPPED;
    assert(mt6762_backlight_desire(&lifecycle, 1023, 0) == -1);
    mt6762_backlight_blank_confirmed(&lifecycle, 0);
    assert(lifecycle.mode == MT6762_BACKLIGHT_STOPPED && lifecycle.desired == 384);
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
