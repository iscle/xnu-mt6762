/* SPDX-License-Identifier: MIT
 * CoreBrightness20F66 legacy property ABI: integer brightness and signed
 * nonnegative16.16 seconds FadePeriod. No floating-point operations in kernel.
 * Float brightness is converted by Apple's code before the registry call.
 */
#ifndef MT6762_APPLE_BACKLIGHT_CORE_H
#define MT6762_APPLE_BACKLIGHT_CORE_H
#include <stdint.h>
/* OSNumber reserves sizes31 and63 for floating payloads. Its integer getters
 * numerically truncate those payloads, so validate the type before conversion.
 * This is a type predicate, not a test of whether a float happens to be whole. */
static inline int mt6762_backlight_integer_type(unsigned number_bits)
{
    return number_bits > 0 && number_bits <= 64 && number_bits != 31 && number_bits != 63;
}
enum { MT6762_BACKLIGHT_ACTIVE, MT6762_BACKLIGHT_BLANKED, MT6762_BACKLIGHT_STOPPED };
struct mt6762_backlight_lifecycle {
    unsigned mode, desired;
    uint64_t fade_us;
};
/* A blanked request is deferred, never a confirmed hardware measurement. */
static inline int mt6762_backlight_desire(struct mt6762_backlight_lifecycle *s,
    unsigned level, uint64_t fade_us)
{
    if (s->mode == MT6762_BACKLIGHT_STOPPED || level > 1023) return -1;
    s->desired = level;
    s->fade_us = fade_us;
    return s->mode == MT6762_BACKLIGHT_BLANKED ? 1 : 0;
}
/* Call only after the zero-level PWM write/readback succeeds. Repeated off
 * must not replace a target that CoreBrightness queued while already blank. */
static inline void mt6762_backlight_blank_confirmed(struct mt6762_backlight_lifecycle *s,
    unsigned previous_confirmed)
{
    if (s->mode != MT6762_BACKLIGHT_ACTIVE) return;
    s->desired = previous_confirmed;
    s->fade_us = 0;
    s->mode = MT6762_BACKLIGHT_BLANKED;
}
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
