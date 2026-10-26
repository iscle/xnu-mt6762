/* SPDX-License-Identifier: MIT -- admission for the measured physical profile. */
#ifndef MTK_NATIVE_DISPLAY_H
#define MTK_NATIVE_DISPLAY_H
#include "pwm_probe.h"

static inline int native_display_admitted(uint64_t framebuffer,
    const volatile struct display_probe_record *display,
    const volatile struct pwm_probe_record *pwm)
{
    if (display->state != DISPLAY_ACCEPTED || display->state_inverse != ~(uint32_t)DISPLAY_ACCEPTED ||
        display->pass != 2 || display->read_mask != 63 || display->sources != 3 ||
        display->layer != 1 || display->tag_base != UINT64_C(0x7ef90000) ||
        display->tag_size != 0x470000 || framebuffer != UINT64_C(0x7f0d4000) ||
        display->datapath != UINT32_C(0x81000001) || display->sbch ||
        pwm->state != PWM_COMPLETE || pwm->state_inverse != ~(uint32_t)PWM_COMPLETE || pwm->pass != 2)
        return 0;
    for (unsigned i = 0; i < 32; ++i)
        if (display->identity[i] != pwm->identity[i]) return 0;
    for (unsigned i = 0; i < 2; ++i) {
        const volatile struct pwm_probe_snapshot *p = &pwm->snapshots[i];
        struct mt6762_pwm_snapshot s = {p->top, p->infra, p->gpio, p->enable,
            p->commit, p->con0, p->con1, p->debug};
        if (p->mask != 23 || !mt6762_display_power(p->power[0],p->power[1],p->power[2]) ||
            !mt6762_pwm_lk_configured(&s)) return 0;
        if (i) {
            const volatile struct pwm_probe_snapshot *first = &pwm->snapshots[0];
            if (p->top != first->top || p->infra != first->infra || p->gpio != first->gpio ||
                p->enable != first->enable || p->commit != first->commit || p->con0 != first->con0 ||
                p->con1 != first->con1 || p->debug != first->debug) return 0;
        }
    }
    return 1;
}
#endif
