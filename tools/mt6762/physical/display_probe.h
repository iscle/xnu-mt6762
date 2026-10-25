/* SPDX-License-Identifier: MIT -- read-only inherited scanout diagnostic. */
#ifndef MTK_DISPLAY_PROBE_H
#define MTK_DISPLAY_PROBE_H
#include <stdint.h>
#include <stddef.h>
#include "fdt_handoff.h"
#include "../hardware/display-touch/mt6762_display_core.h"

enum display_probe_state {
    DISPLAY_UNTOUCHED, DISPLAY_TAG, DISPLAY_BOUNDS, DISPLAY_RESERVATION,
    DISPLAY_POWER, DISPLAY_GATES, DISPLAY_SOURCES, DISPLAY_SCANOUT,
    DISPLAY_ACCEPTED, DISPLAY_READING, DISPLAY_DATAPATH
};
/* Only fields selected by read_mask were observed. Pass is one-based for MMIO.
 * The immutable build identity matches the separate loader phase record.
 * A completed record is evidence of validation, never native ownership. */
struct display_probe_record {
    uint8_t magic[8]; uint32_t version, size; uint8_t identity[32];
    uint32_t state, pass, read_mask, state_inverse;
    uint64_t tag_base, tag_size;
    uint32_t tag_present, tag_found;
    uint32_t power[3], gates, sources, layer;
    struct mt6762_ovl_snapshot scanout[4];
    uint32_t datapath, sbch, reserved[18];
};
_Static_assert(sizeof(struct display_probe_record) == 512, "display record size");
_Static_assert(offsetof(struct display_probe_record, state) == 48, "display state offset");
_Static_assert(offsetof(struct display_probe_record, scanout) == 112, "display snapshot offset");
extern volatile struct display_probe_record physical_display;
struct display_probe_io {
    void *context;
    uint32_t (*read)(void *, uint64_t);
    void (*barrier)(void *);
};
static inline void display_probe_commit(volatile struct display_probe_record *r,
    const struct display_probe_io *io, uint32_t state)
{
    r->state_inverse = ~state;
    io->barrier(io->context);
    r->state = state;
    io->barrier(io->context);
}
static inline uint64_t display_probe_console(const struct mtk_fdt_framebuffer *tag,
    int reserved, const struct display_probe_io *io, volatile struct display_probe_record *r)
{
    display_probe_commit(r, io, DISPLAY_READING);
    r->tag_base = tag->base; r->tag_size = tag->size;
    r->tag_present = tag->present; r->tag_found = tag->found;
    r->pass = 0; r->read_mask = 1;
    uint32_t failure = DISPLAY_TAG;
    if (!(tag->present & 16) || tag->found != 1) goto refuse;
    struct mt6762_fb_layout fb = {tag->base, 0x144000, tag->base, tag->size,
        384, 854, 1536, 1, 0};
    failure = DISPLAY_BOUNDS;
    if (!mt6762_fb_bounds(&fb)) goto refuse;
    failure = DISPLAY_RESERVATION;
    if (!reserved) goto refuse;
    uint64_t selected = 0;
    for (unsigned pass = 1; pass <= 2; ++pass) {
        r->pass = pass; r->read_mask = 1;
        for (unsigned n = 0; n < 3; ++n)
            r->power[n] = io->read(io->context, n == 0 ? 0x10006180 : n == 1 ? 0x10006184 : 0x1000630c);
        r->read_mask |= 2;
        failure = DISPLAY_POWER;
        if (!mt6762_display_power(r->power[0], r->power[1], r->power[2])) goto refuse;
        r->gates = io->read(io->context, 0x14000100); r->read_mask |= 4;
        failure = DISPLAY_GATES;
        if (r->gates & ((1u<<7)|(1u<<10)|(1u<<17)|(1u<<19)|(1u<<20)|(1u<<28))) goto refuse;
        uint32_t sources = io->read(io->context, 0x1400b02c);
        r->sources = sources; r->read_mask |= 8;
        failure = DISPLAY_SOURCES;
        if (!sources || (sources & ~15u)) goto refuse;
        fb.layer = sources == 1 ? 0 : sources == 2 ? 1 : sources == 4 ? 2 : 3;
        r->layer = fb.layer;
        /* Record every enabled hardware layer, including rejected multi-layer
         * states. Bounds/power/gates still precede every display-block read.
         * Admission allows either the single layer or the measured LK menu
         * profile, after validating global controls below. */
        for (unsigned index = 0; index < 4; ++index) {
            if (!(sources & (1u << index))) continue;
            uint64_t layer = index * 0x20;
#define R(address) io->read(io->context, (address))
            struct mt6762_ovl_snapshot s = {
                R(0x1400b00c), sources, R(0x1400b324), R(0x1400b020),
                R(0x1400b030+layer), R(0x1400bf40+layer), R(0x1400b044+layer),
                R(0x1400b038+layer), R(0x1400b03c+layer), R(0x1400b04c+layer),
                R(0x1400b0c0+layer), R(0x1400d010), R(0x14014000),
                R(0x14014014), R(0x14014018), R(0x1401402c),
                R(0x1401401c), R(0x14014020), R(0x14014024), R(0x14014028)
            };
#undef R
            r->scanout[index] = s;
        }
        r->read_mask |= 16;
        r->datapath = io->read(io->context, 0x1400b024);
        r->sbch = io->read(io->context, 0x1400b3a0);
        r->read_mask |= 32;
        failure = DISPLAY_DATAPATH;
        /* Allow only SMI IDs, output rounding disable, GCLAST and clamp.
         * Reject GPU/PQ/bypass/interlace/wide-gamut/background routing and
         * all SBCH transparency/constant caching. Never write these modes. */
        if ((r->datapath & ~UINT32_C(0x05000009)) || r->sbch) goto refuse;
        uint64_t candidate = 0;
        if (sources == 3) {
            struct mt6762_ovl_snapshot layers[2] = {r->scanout[0], r->scanout[1]};
            candidate = mt6762_boot_menu_buffer(tag->base, tag->size, layers);
            r->layer = 1;
        } else if (!(sources & (sources-1))) {
            struct mt6762_ovl_snapshot s = r->scanout[fb.layer];
            if (mt6762_ovl_matches(&fb, &s)) candidate = tag->base;
        } else {
            failure = DISPLAY_SOURCES; goto refuse;
        }
        failure = DISPLAY_SCANOUT;
        if (!candidate || (pass == 2 && selected != candidate)) goto refuse;
        selected = candidate;
    }
    display_probe_commit(r, io, DISPLAY_ACCEPTED);
    return selected;
refuse:
    display_probe_commit(r, io, failure);
    return 0;
}
#endif
