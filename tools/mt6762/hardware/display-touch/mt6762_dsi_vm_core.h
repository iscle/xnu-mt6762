/* SPDX-License-Identifier: MIT
 * Experimental, unwired MT6765 DSI video-mode short-command transport.
 * Register/packet evidence: panel-lifecycle-audit.json. This is not an
 * initialized native driver and does not establish a safe panel sleep cycle.
 */
#ifndef MT6762_DSI_VM_CORE_H
#define MT6762_DSI_VM_CORE_H
#include <stdint.h>
#include <stddef.h>
struct mt6762_dsi_vm_io {
    void *context;
    /* Must verify exclusive DSI/GCE/IRQ-ack ownership, initialized powered
     * clocks/PHY/video timing, preserved rails/reset and usable MMIO. A bare
     * DT boolean is insufficient. Return0 only for admitted hardware state. */
    int (*verify_owned_inherited)(void *);
    /* First-command admission must separately establish that no inherited VM
     * request is in flight. Ownership, START low and stale DONE are each
     * insufficient. No physical implementation of this proof exists here.
     * Return0 only after an external, verified idle handoff/drain protocol. */
    int (*admit_initial_idle)(void *);
    uint32_t (*read32)(void *, unsigned);
    void (*write32)(void *, unsigned, uint32_t);
    void (*barrier)(void *);
    void (*delay_us)(void *, unsigned);
};
/* Initialize to zero once per admitted ownership lifetime. Do not clear a
 * fault/reseed this state to bypass a pending inherited request. */
struct mt6762_dsi_vm_state {
    unsigned faulted, own_completed;
    uint32_t completed_packet;
};
enum { MT6762_DSI_ARGUMENT = -1, MT6762_DSI_UNAVAILABLE = -2,
       MT6762_DSI_READBACK = -3, MT6762_DSI_TIMEOUT = -4 };
#define MT6762_DSI_VM_DONE UINT32_C(0x20)
#define MT6762_DSI_VM_START UINT32_C(0x10000)

/* Only the exact stock short DCS command+one-zero-byte form. Long vendor
 * initialization packets, reads/BTA, command mode and dual DSI are excluded.
 * Caller serializes all invocations and supplies a validated timeout budget.
 * MMIO that never returns cannot be recovered by this bounded poll loop. */
static inline int mt6762_dsi_vm_short_zero(struct mt6762_dsi_vm_state *s,
    const struct mt6762_dsi_vm_io *io, uint8_t command,
    unsigned poll_us, unsigned polls)
{
    if (!s || !io || !io->verify_owned_inherited || !io->admit_initial_idle || !io->read32 || !io->write32 ||
        !io->barrier || !io->delay_us || !poll_us || !polls ||
        (uint64_t)poll_us * polls > UINT64_C(1000000) ||
        (command != 0x10 && command != 0x11 && command != 0x28 && command != 0x29))
        return MT6762_DSI_ARGUMENT;
    if (s->faulted) return MT6762_DSI_UNAVAILABLE;
    if (io->verify_owned_inherited(io->context)) goto unavailable;
    uint32_t mode = io->read32(io->context, 0x14);
    uint32_t control = io->read32(io->context, 0x130);
    uint32_t start = io->read32(io->context, 0x00);
    uint32_t initial_status = io->read32(io->context, 0x0c);
    /* A high inherited trigger may still own the command slot even if stale
     * DONE is high. Only retain our own fully completed/acknowledged trigger.
     * Low START alone does not prove an idle command engine either. */
    if (!s->own_completed) {
        if ((start & MT6762_DSI_VM_START) || io->admit_initial_idle(io->context)) goto unavailable;
    } else if (control != s->completed_packet || (initial_status & MT6762_DSI_VM_DONE)) {
        goto unavailable;
    }
    /* SYNC_EVENT video mode, VM commands already enabled during VFP. The
     * transport neither enables this facility nor changes video timing. */
    if ((mode & 3) != 2 || (control & 0x3d) != 0x21 || (start & UINT32_C(0x14)) ||
        (io->read32(io->context, 0x04) & 0xf2) ||
        (initial_status & 0x7080)) goto unavailable;
    /* Preserve low configuration bits except LONG_PKT. DCS short write with
     * one parameter has data ID0x15, command in16..23 and zero in24..31. */
    uint32_t packet = (control & UINT32_C(0xfd)) | UINT32_C(0x1500) |
        ((uint32_t)command << 16);
    s->own_completed = 0;
    io->write32(io->context, 0x130, packet);
    io->barrier(io->context);
    if (io->read32(io->context, 0x130) != packet) goto readback;
    /* INTSTA is write-zero-to-clear, unlike the thermal controller's W1C.
     * Literal complement preserves all other status, including newly set bits. */
    io->write32(io->context, 0x0c, ~MT6762_DSI_VM_DONE);
    io->barrier(io->context);
    if (io->read32(io->context, 0x0c) & MT6762_DSI_VM_DONE) goto readback;
    /* Other one-shot requests were rejected before the first write. */
    io->write32(io->context, 0x00, start & ~MT6762_DSI_VM_START);
    io->barrier(io->context);
    io->write32(io->context, 0x00, start | MT6762_DSI_VM_START);
    io->barrier(io->context);
    for (unsigned i = 0; i < polls; i++) {
        if (io->verify_owned_inherited(io->context)) goto unavailable;
        uint32_t status = io->read32(io->context, 0x0c);
        if ((status & UINT32_C(0x7080)) ||
            (io->read32(io->context, 0x04) & 0xf2)) goto unavailable;
        if (status & MT6762_DSI_VM_DONE) {
            io->barrier(io->context);
            if (io->read32(io->context, 0x14) != mode ||
                io->read32(io->context, 0x130) != packet) goto readback;
            io->write32(io->context, 0x0c, ~MT6762_DSI_VM_DONE);
            io->barrier(io->context);
            uint32_t acknowledged = io->read32(io->context, 0x0c);
            if (acknowledged & MT6762_DSI_VM_DONE) goto readback;
            if (acknowledged & UINT32_C(0x7080)) goto unavailable;
            s->completed_packet = packet;
            s->own_completed = 1;
            return 0;
        }
        io->delay_us(io->context, poll_us);
    }
    s->faulted = 1;
    return MT6762_DSI_TIMEOUT;
readback:
    s->faulted = 1;
    s->own_completed = 0;
    return MT6762_DSI_READBACK;
unavailable:
    s->faulted = 1;
    s->own_completed = 0;
    return MT6762_DSI_UNAVAILABLE;
}
#endif
