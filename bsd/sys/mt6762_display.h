/* SPDX-License-Identifier: MIT */
#ifndef MT6762_DISPLAY_H
#define MT6762_DISPLAY_H
#include <sys/types.h>
#ifdef __cplusplus
extern "C" {
#endif
void mt6762_display_init(void);
/* Returns1 for a validated inherited native framebuffer, or the existing lab
 * path when no native handoff is requested. Native failures always return0. */
int mt6762_display_usable(uintptr_t virtual_base, unsigned width,
    unsigned height, unsigned stride, unsigned depth);
/* Explicit native API, linear duty0..1023. No Apple brightness ABI implied. */
int mt6762_brightness_set(unsigned level);
/* Reads current duty/enable after the same prerequisite checks, no writes. */
int mt6762_brightness_get(unsigned *level);
void mt6762_touch_init(void);
#ifdef __cplusplus
}
#endif
#endif
