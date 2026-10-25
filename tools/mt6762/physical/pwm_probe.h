/* SPDX-License-Identifier: MIT -- passive bootloader brightness snapshot. */
#ifndef MTK_PWM_PROBE_H
#define MTK_PWM_PROBE_H
#include <stdint.h>
#include <stddef.h>
#include "display_probe.h"

/* Groups are marked only after all their reads finish. A snapshot does not
 * grant ownership, prove the external backlight wiring, or enable any clock. */
enum pwm_probe_state { PWM_UNTOUCHED, PWM_READING, PWM_UNAVAILABLE, PWM_COMPLETE };
enum pwm_probe_mask { PWM_POWER=1, PWM_CLOCKS=2, PWM_PIN=4, PWM_ULPOSC=8, PWM_BLOCK=16 };
struct pwm_probe_snapshot {
    uint32_t mask, power[3], top, infra, gpio, ulposc;
    uint32_t enable, commit, con0, con1, debug, reserved[3];
};
struct pwm_probe_record {
    uint8_t magic[8]; uint32_t version, size; uint8_t identity[32];
    uint32_t state, state_inverse, pass, reserved0;
    struct pwm_probe_snapshot snapshots[2];
    uint32_t reserved[16];
};
_Static_assert(sizeof(struct pwm_probe_snapshot) == 64, "PWM snapshot size");
_Static_assert(sizeof(struct pwm_probe_record) == 256, "PWM record size");
_Static_assert(offsetof(struct pwm_probe_record, snapshots) == 64, "PWM snapshot offset");
extern volatile struct pwm_probe_record physical_pwm;

static inline void pwm_probe_commit(volatile struct pwm_probe_record *r,
    const struct display_probe_io *io, uint32_t state)
{
    r->state_inverse = ~state;
    io->barrier(io->context);
    r->state = state;
    io->barrier(io->context);
}

static inline void pwm_probe_capture(const struct display_probe_io *io,
    volatile struct pwm_probe_record *r)
{
    pwm_probe_commit(r, io, PWM_READING);
    for (unsigned pass = 0; pass < 2; ++pass) {
        r->pass = pass + 1;
        volatile struct pwm_probe_snapshot *s = &r->snapshots[pass];
#define R(address) io->read(io->context, (address))
        s->power[0] = R(0x10006180);
        s->power[1] = R(0x10006184);
        s->power[2] = R(0x1000630c);
        s->mask |= PWM_POWER;
        /* Always-on clock/pin registers precede any peripheral-block access. */
        s->top = R(0x10000080);
        s->infra = R(0x100010ac);
        s->mask |= PWM_CLOCKS;
        s->gpio = R(0x10005350); /* GPIO43: MODE bits15:12, DISP_PWM mux1. */
        s->mask |= PWM_PIN;
        if (!mt6762_display_power(s->power[0], s->power[1], s->power[2]) ||
            (s->top & (1u << 31)) || (s->infra & (1u << 2))) goto unavailable;
        if (((s->top >> 24) & 3) >= 2) {
            s->ulposc = R(0x10006458);
            s->mask |= PWM_ULPOSC;
            if ((s->ulposc & 5) != 5) goto unavailable;
        }
        /* Only passive register reads. COMMIT and DEBUG are not written. */
        s->enable = R(0x1100e000);
        s->commit = R(0x1100e00c);
        s->con0 = R(0x1100e018);
        s->con1 = R(0x1100e01c);
        s->debug = R(0x1100e080);
        s->mask |= PWM_BLOCK;
        io->barrier(io->context);
#undef R
    }
    pwm_probe_commit(r, io, PWM_COMPLETE);
    return;
unavailable:
    pwm_probe_commit(r, io, PWM_UNAVAILABLE);
}
#endif
