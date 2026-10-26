/* SPDX-License-Identifier: MIT
 * Portable AXS state tracking. No hardware access or runtime initialization.
 * Caller serializes calls and supplies a monotonic microsecond clock. Call
 * axs_state_expire periodically even when no packets arrive, and release_all
 * before stopping a device, so transport loss cannot leave fingers held.
 */
#ifndef MT6762_AXS_TOUCH_STATE_H
#define MT6762_AXS_TOUCH_STATE_H
#include "axs_touch.h"
/* Values match bsd/sys/hakios.input.h. Sink adapts to hakios_touch_post(). */
enum { AXS_DOWN = 1, AXS_MOVE = 2, AXS_UP = 3 };
typedef void (*axs_event_sink)(void *, unsigned type, unsigned id, unsigned x, unsigned y);
struct axs_state {
    struct { uint16_t x, y; } point[AXS_TOUCH_MAX_CONTACTS];
    uint16_t x_max, y_max;
    uint8_t active, clock_seen;
    uint64_t last_clock_us, last_valid_us, timeout_us;
    axs_event_sink emit;
    void *context;
};
static inline int axs_state_init(struct axs_state *s, unsigned xmax, unsigned ymax,
    uint64_t timeout_us, axs_event_sink emit, void *context)
{
    if (!s || !xmax || !ymax || xmax > 4095 || ymax > 4095 || !timeout_us || !emit) return -1;
    *s = (struct axs_state){0};
    s->x_max = (uint16_t)xmax; s->y_max = (uint16_t)ymax;
    s->timeout_us = timeout_us; s->emit = emit; s->context = context;
    return 0;
}
static inline void axs_state_release_all(struct axs_state *s)
{
    if (!s || !s->emit) return;
    uint8_t active = s->active;
    s->active = 0;
    for (unsigned i = 0; i < AXS_TOUCH_MAX_CONTACTS; ++i)
        if (active & (1u << i)) s->emit(s->context, AXS_UP, i, s->point[i].x, s->point[i].y);
}
/* Returns -1 for invalid state/backwards clock, 1 if expired, otherwise0. */
static inline int axs_state_expire(struct axs_state *s, uint64_t now_us)
{
    if (!s || !s->emit || !s->timeout_us) return -1;
    if (s->clock_seen && now_us < s->last_clock_us) {
        axs_state_release_all(s);
        return -1;
    }
    s->last_clock_us = now_us; s->clock_seen = 1;
    if (s->active && now_us - s->last_valid_us >= s->timeout_us) {
        axs_state_release_all(s);
        return 1;
    }
    return 0;
}
/* Returns1 for valid touch frame,0 for status frame,-1 for malformed input.
 * Validation completes before posting any new contact. Malformed frames release
 * every held contact; status frames preserve state only until the deadline.
 * axis maxima are inclusive reported ABS maxima (this phone:384 and854).
 */
static inline int axs_state_feed(struct axs_state *s, const uint8_t *packet,
    size_t length, uint64_t now_us)
{
    struct axs_frame f;
    uint8_t seen = 0;
    if (axs_state_expire(s, now_us) < 0) return -1;
    int result = axs_touch_decode(packet, length, &f);
    if (!result) return 0;
    if (result < 0 || (packet[1] & 15) > AXS_TOUCH_MAX_CONTACTS || f.count != (packet[1] & 15)) goto malformed;
    for (unsigned i = 0; i < f.count; ++i) {
        const struct axs_contact *c = &f.contacts[i];
        if ((seen & (1u << c->id)) || c->event == 3 || c->x > s->x_max || c->y > s->y_max) goto malformed;
        seen |= (uint8_t)(1u << c->id);
    }
    /* Release missing/up contacts before new downs, using their last position. */
    for (unsigned id = 0; id < AXS_TOUCH_MAX_CONTACTS; ++id) {
        if ((s->active & ~f.active_mask) & (1u << id))
            s->emit(s->context, AXS_UP, id, s->point[id].x, s->point[id].y);
    }
    for (unsigned i = 0; i < f.count; ++i) {
        const struct axs_contact *c = &f.contacts[i];
        if (!(f.active_mask & (1u << c->id))) continue;
        unsigned x = (unsigned)c->x * 65535u / s->x_max;
        unsigned y = (unsigned)c->y * 65535u / s->y_max;
        if (!(s->active & (1u << c->id))) s->emit(s->context, AXS_DOWN, c->id, x, y);
        else if (x != s->point[c->id].x || y != s->point[c->id].y)
            s->emit(s->context, AXS_MOVE, c->id, x, y);
        s->point[c->id].x = (uint16_t)x; s->point[c->id].y = (uint16_t)y;
    }
    s->active = f.active_mask; s->last_valid_us = now_us;
    return 1;
malformed:
    axs_state_release_all(s);
    return -1;
}
#endif
