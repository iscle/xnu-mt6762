/* SPDX-License-Identifier: MIT
 * Synthetic W0C/packet/fresh-completion contract, not a physical DSI test. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "mt6762_dsi_vm_core.h"
struct fake {
    uint32_t regs[0x134 / 4];
    unsigned writes, triggers, delays, denied, stale, timeout, badread, modechange;
    unsigned idle_unproven, admissions, acknowledgements, drop_final_ack;
    unsigned offsets[16];
    uint32_t values[16];
};
static int verify(void *p) { return ((struct fake *)p)->denied ? -1 : 0; }
static int admit_idle(void *p)
{
    struct fake *f = p;
    f->admissions++;
    return f->idle_unproven ? -1 : 0;
}
static uint32_t read32(void *p, unsigned off)
{
    struct fake *f = p;
    if (f->badread && off == 0x130 && f->writes) return 0;
    return f->regs[off / 4];
}
static void write32(void *p, unsigned off, uint32_t value)
{
    struct fake *f = p;
    assert(f->writes < 16 && (off == 0 || off == 0xc || off == 0x130));
    f->offsets[f->writes] = off; f->values[f->writes++] = value;
    if (off == 0xc) {
        assert(value == ~MT6762_DSI_VM_DONE);
        f->acknowledgements++;
        if (!f->stale && !(f->drop_final_ack && f->acknowledgements == 2))
            f->regs[off / 4] &= value;
    } else {
        if (off == 0 && !(f->regs[0] & MT6762_DSI_VM_START) && (value & MT6762_DSI_VM_START)) f->triggers++;
        f->regs[off / 4] = value;
    }
}
static void barrier(void *p) { (void)p; }
static void delay(void *p, unsigned us)
{
    struct fake *f = p;
    assert(us == 10);
    f->delays++;
    /* A different event can arrive after the first acknowledgement. The
     * completion acknowledgement must preserve it, not replay an old mask. */
    if (f->triggers && !f->timeout) f->regs[0xc / 4] |= MT6762_DSI_VM_DONE | 0x10;
    if (f->modechange) f->regs[0x14 / 4] = 0;
}
static void reset(struct fake *f)
{
    memset(f, 0, sizeof(*f));
    f->regs[0] = 1;
    f->regs[0xc / 4] = MT6762_DSI_VM_DONE | 8; /* old completion plus unrelated frame event */
    f->regs[0x14 / 4] = 2;
    f->regs[0x130 / 4] = 0xaabb3923; /* prior long packet, configured VFP */
}
int main(void)
{
    struct fake f;
    struct mt6762_dsi_vm_state state = {0};
    const struct mt6762_dsi_vm_io io = {&f, verify, admit_idle, read32, write32, barrier, delay};
    reset(&f);
    assert(!mt6762_dsi_vm_short_zero(&state, &io, 0x28, 10, 4));
    assert(f.regs[0x130 / 4] == 0x281521 && f.triggers == 1 && f.delays == 1);
    assert(f.regs[0] == 0x10001 && f.regs[0xc / 4] == 0x18);
    assert(f.writes == 5 && f.offsets[0] == 0x130 && f.offsets[1] == 0xc);
    assert(f.offsets[2] == 0 && f.values[2] == 1 && f.values[3] == 0x10001);
    assert(!mt6762_dsi_vm_short_zero(&state, &io, 0x10, 10, 4));
    assert(f.triggers == 2 && f.admissions == 1 && state.own_completed); /* only our completed trigger */
    /* A high inherited trigger is not our prior completion. Neither stale
     * DONE high nor DONE low admits overwriting its command packet. */
    for (unsigned done = 0; done < 2; done++) {
        reset(&f); state = (struct mt6762_dsi_vm_state){0};
        f.regs[0] |= MT6762_DSI_VM_START;
        if (!done) f.regs[0xc / 4] &= ~MT6762_DSI_VM_DONE;
        assert(mt6762_dsi_vm_short_zero(&state, &io, 0x28, 10, 4) == MT6762_DSI_UNAVAILABLE);
        assert(!f.writes && !f.triggers && !f.admissions);
    }
    /* Even low START requires independent initial idle admission. */
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.idle_unproven = 1;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x28, 10, 4) == MT6762_DSI_UNAVAILABLE);
    assert(!f.writes && f.admissions == 1);
    /* A dropped final W0C write must not create an own-completion token. */
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.drop_final_ack = 1;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x28, 10, 4) == MT6762_DSI_READBACK);
    assert(state.faulted && !state.own_completed && f.triggers == 1);
    unsigned failed_writes = f.writes;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x29, 10, 4) < 0 && f.writes == failed_writes);
    /* Loss of the previous packet/cleared status invalidates retained proof. */
    reset(&f); state = (struct mt6762_dsi_vm_state){0};
    assert(!mt6762_dsi_vm_short_zero(&state, &io, 0x28, 10, 4));
    f.regs[0x130 / 4] ^= 0x10000; failed_writes = f.writes;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x29, 10, 4) < 0 && f.writes == failed_writes);
    reset(&f); state = (struct mt6762_dsi_vm_state){0};
    assert(!mt6762_dsi_vm_short_zero(&state, &io, 0x28, 10, 4));
    f.regs[0xc / 4] |= MT6762_DSI_VM_DONE; failed_writes = f.writes;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x29, 10, 4) < 0 && f.writes == failed_writes);
    const uint8_t commands[] = {0x10, 0x11, 0x28, 0x29};
    for (unsigned i = 0; i < sizeof(commands); i++) {
        reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.regs[0] |= 0x100;
        assert(!mt6762_dsi_vm_short_zero(&state, &io, commands[i], 10, 4));
        assert(f.regs[0x130 / 4] == ((uint32_t)commands[i] << 16 | 0x1521));
        assert(f.values[2] == 0x101 && f.values[3] == 0x10101 && f.regs[0] == 0x10101);
    }
    const unsigned invalid_modes[] = {0, 1, 3};
    for (unsigned i = 0; i < 3; i++) {
        reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.regs[0x14 / 4] = invalid_modes[i];
        assert(mt6762_dsi_vm_short_zero(&state, &io, 0x11, 10, 4) < 0 && !f.writes);
    }
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.denied = 1;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x11, 10, 4) < 0 && !f.writes);
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.regs[0] |= 4;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x11, 10, 4) < 0 && !f.writes);
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.regs[0] |= 16;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x11, 10, 4) < 0 && !f.writes);
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.stale = 1;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x11, 10, 4) == MT6762_DSI_READBACK && !f.triggers);
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.timeout = 1;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x11, 10, 4) == MT6762_DSI_TIMEOUT && f.delays == 4);
    unsigned writes = f.writes;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x29, 10, 4) < 0 && f.writes == writes);
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.badread = 1;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x29, 10, 4) == MT6762_DSI_READBACK && !f.triggers);
    reset(&f); state = (struct mt6762_dsi_vm_state){0}; f.modechange = 1;
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x29, 10, 4) == MT6762_DSI_READBACK);
    reset(&f); state = (struct mt6762_dsi_vm_state){0};
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0xbb, 10, 4) == MT6762_DSI_ARGUMENT && !f.writes);
    assert(mt6762_dsi_vm_short_zero(&state, &io, 0x29, 0, 4) == MT6762_DSI_ARGUMENT && !f.writes);
    puts("Synthetic DSI VM short packet/W0C/fresh-completion tests passed");
    return 0;
}
