/* SPDX-License-Identifier: MIT
 * Narrow inherited OVL0/BGRA8888 scanout validation and DISP_PWM duty update.
 * Register definitions: supplied MT6765 BSP ddp_reg_ovl.h/ddp_reg_dma.h,
 * ddp_info.h, ddp_reg_dsi.h, clk-mt6765-pg.c; stock PWM addresses in audit JSON.
 * This does not initialize clocks, rails, DSI, M4U or a panel.
 */
#ifndef MT6762_DISPLAY_CORE_H
#define MT6762_DISPLAY_CORE_H
#include <stdint.h>
#include <stddef.h>
struct mt6762_fb_layout {
    uint64_t physical, size, reserved_base, reserved_size;
    uint32_t width, height, stride, format, layer;
};
static inline int mt6762_fb_bounds(const struct mt6762_fb_layout *f)
{
    if (!f || f->width != 384 || f->height != 854 || f->format != 1 || f->layer > 3 ||
        f->stride < f->width * 4 || f->stride > 65535 || (f->stride & 3) ||
        !f->physical || (f->physical & 0x3fff) || f->physical > UINT32_MAX ||
        (f->reserved_base & 0x3fff) || (f->reserved_size & 0x3fff) ||
        f->size > 16 * 1024 * 1024 ||
        (((uint64_t)f->stride * f->height + 0x3fff) & ~UINT64_C(0x3fff)) > f->size ||
        f->physical < f->reserved_base || f->size > f->reserved_size ||
        f->physical - f->reserved_base > f->reserved_size - f->size ||
        f->size > (uint64_t)UINT32_MAX + 1 - f->physical ||
        f->reserved_size > UINT64_MAX - f->reserved_base) return 0;
    return 1;
}
static inline int mt6762_display_power(uint32_t status, uint32_t status2, uint32_t con)
{
    /* Both status copies ON, reset released, power bits ON, isolation/clock
     * disable/SRAM powerdown/SRAM acknowledgement all clear. */
    return (status & 8) && (status2 & 8) && (con & 0x111f) == 0x0d;
}
struct mt6762_ovl_snapshot {
    uint32_t en, sources, ext_sources, roi, con, address, pitch, size, offset, clip, rdma;
    uint32_t downstream_rdma, dsi_start, dsi_mode, dsi_lanes, dsi_active;
    uint32_t dsi_ps, dsi_vsa, dsi_vbp, dsi_vfp;
};
static inline int mt6762_ovl_matches(const struct mt6762_fb_layout *f,
    const struct mt6762_ovl_snapshot *s)
{
    uint32_t dimensions = f->width | (f->height << 16);
    /* Reject rotation, colour keys, matrix conversion, local/constant source,
     * extended layers, manual format and byte/RGB swaps. Alpha is opaque or
     * disabled. Only the one known memory layer may contribute to scanout. */
    return mt6762_fb_bounds(f) && (s->en & 1) && s->sources == (1u << f->layer) &&
        !(s->ext_sources & 7) && s->roi == dimensions &&
        (s->con & 0xfffffe00u) == 0x2000 && (!(s->con & 0x100) || (s->con & 255) == 255) &&
        s->address == f->physical && (s->pitch & 0xffff) == f->stride &&
        s->size == dimensions && !s->offset && !s->clip && (s->rdma & 1) &&
        (s->downstream_rdma & 0x13) == 1 && /* RDMA direct-link, no reset */
        (s->dsi_start & 1) && (s->dsi_mode & 0x1f0303) == 2 &&
        ((s->dsi_lanes >> 2) & 15) == 7 && (s->dsi_active & 0x3fff) == f->height &&
        (s->dsi_ps & 0x03077fffu) == ((2u << 16) | 1152) &&
        s->dsi_vsa == 2 && s->dsi_vbp == 20 && s->dsi_vfp == 170;
}
struct mt6762_pwm_io {
    void *context;
    uint32_t (*read)(void *, unsigned offset);
    void (*write)(void *, unsigned offset, uint32_t value);
    void (*barrier)(void *);
};
static inline int mt6762_pwm_configured(uint32_t con0, uint32_t con1,
    uint32_t top, uint32_t infra)
{
    return ((con0 >> 16) & 1023) == 3 && (con1 & 1023) == 1023 &&
        !(top & 0x80000000u) && ((top >> 24) & 3) == 3 && !(infra & 4);
}
static inline int mt6762_pwm_program(const struct mt6762_pwm_io *io, unsigned level)
{
    if (!io || !io->read || !io->write || !io->barrier || level > 1023) return -1;
    uint32_t con1 = io->read(io->context, 0x1c);
    uint32_t en = io->read(io->context, 0);
    /* Period remains1023. Reject a changed configuration before any write. */
    if ((con1 & 1023) != 1023) return -1;
    con1 = (con1 & ~0x1fff0000u) | ((level ? level : 1) << 16);
    en = (en & ~1u) | (level != 0);
    io->write(io->context, 0x1c, con1); io->barrier(io->context);
    io->write(io->context, 0, en); io->barrier(io->context);
    io->write(io->context, 0x0c, 1); io->barrier(io->context);
    io->write(io->context, 0x0c, 0); io->barrier(io->context);
    return ((io->read(io->context, 0x1c) & 0x1fff03ffu) == (con1 & 0x1fff03ffu) &&
        (io->read(io->context, 0) & 1) == (en & 1)) ? 0 : -1;
}
#endif
