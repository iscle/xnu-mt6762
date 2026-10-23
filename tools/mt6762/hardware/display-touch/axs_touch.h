/* SPDX-License-Identifier: MIT
 * Independently reconstructed from the supplied stock AXS driver.
 * Evidence: axs_ts_interrupt 0xffffff8008a26b50, packet decode +0x264.
 * This is a packet decoder, not a complete device or IOHID driver.
 */
#ifndef MT6762_AXS_TOUCH_H
#define MT6762_AXS_TOUCH_H
#include <stddef.h>
#include <stdint.h>

#define AXS_TOUCH_ADDRESS 0x3b
#define AXS_TOUCH_PACKET_BYTES 32
#define AXS_TOUCH_MAX_CONTACTS 5
struct axs_contact {
    uint16_t x, y;
    uint8_t id, event, pressure, area;
};
struct axs_frame {
    uint8_t count;
    uint8_t active_mask;
    struct axs_contact contacts[AXS_TOUCH_MAX_CONTACTS];
};
/* 1 valid touch frame, 0 non-touch/status frame, -1 invalid argument/header.
 * Zero-contact valid frames release all contacts. For non-touch/errors retain
 * previous state until the caller's independent timeout/reset policy fires.
 * Coordinates are raw; caller validates/transforms against the actual panel.
 */
static inline int
axs_touch_decode(const uint8_t *p, size_t n, struct axs_frame *out)
{
    struct axs_frame f = {0};
    if (!p || !out || n != AXS_TOUCH_PACKET_BYTES) return -1;
    if (p[0] != 0) return 0;
    if (p[1] & 0xf0) return -1;
    unsigned count = p[1] & 15;
    if (count > AXS_TOUCH_MAX_CONTACTS) count = AXS_TOUCH_MAX_CONTACTS;
    for (unsigned i = 0; i < count; ++i) {
        const uint8_t *r = p + 2 + 6*i;
        unsigned id = r[2] >> 4;
        if (id >= AXS_TOUCH_MAX_CONTACTS) break;
        struct axs_contact *c = &f.contacts[f.count++];
        c->x = (uint16_t)(((r[0] & 15) << 8) | r[1]);
        c->y = (uint16_t)(((r[2] & 15) << 8) | r[3]);
        c->event = r[0] >> 6;
        c->id = (uint8_t)id;
        c->pressure = r[4];
        c->area = r[5] >> 4;
        if (c->event == 0 || c->event == 2) {
            if (!c->pressure) c->pressure = 63;
            if (!c->area) c->area = 9;
            f.active_mask |= (uint8_t)(1u << id);
        }
    }
    *out = f;
    return 1;
}
#endif
