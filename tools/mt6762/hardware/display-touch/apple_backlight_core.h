/* SPDX-License-Identifier: MIT
 * CoreBrightness20F66 legacy property ABI: integer brightness and signed
 * nonnegative16.16 seconds FadePeriod. No floating-point operations in kernel.
 * Float brightness is converted by Apple's code before the registry call.
 */
#ifndef MT6762_APPLE_BACKLIGHT_CORE_H
#define MT6762_APPLE_BACKLIGHT_CORE_H
#include <stdint.h>
static inline int mt6762_backlight_request(uint64_t brightness, uint64_t fade_fixed,
    uint64_t *duration_us)
{
    if (!duration_us || brightness > 1023 || fade_fixed > INT32_MAX) return -1;
    *duration_us = (fade_fixed * UINT64_C(1000000)) >> 16;
    return 0;
}
static inline unsigned mt6762_backlight_step(unsigned from, unsigned to,
    uint64_t elapsed_us, uint64_t duration_us)
{
    if (!duration_us || elapsed_us >= duration_us) return to;
    if (to >= from) return from + (unsigned)((to - from) * elapsed_us / duration_us);
    return from - (unsigned)((from - to) * elapsed_us / duration_us);
}
#endif
