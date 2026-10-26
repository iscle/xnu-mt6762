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
static inline int mt6762_ovl_matches_sources(const struct mt6762_fb_layout *f,
    const struct mt6762_ovl_snapshot *s, uint32_t sources)
{
    uint32_t dimensions = f->width | (f->height << 16);
    /* Reject rotation, colour keys, matrix conversion, local/constant source,
     * extended layers, manual format and byte/RGB swaps. Alpha is opaque or
     * disabled. Only the one known memory layer may contribute to scanout. */
    return mt6762_fb_bounds(f) && (s->en & 1) && s->sources == sources &&
        !(s->ext_sources & 7) && s->roi == dimensions &&
        (s->con & 0xfffffe00u) == 0x2000 && (!(s->con & 0x100) || (s->con & 255) == 255) &&
        s->address == f->physical && s->pitch == f->stride &&
        s->size == dimensions && !s->offset && !s->clip && (s->rdma & 1) &&
        (s->downstream_rdma & 0x13) == 1 && /* RDMA direct-link, no reset */
        (s->dsi_start & 1) && (s->dsi_mode & 0x1f0303) == 2 &&
        ((s->dsi_lanes >> 2) & 15) == 7 && (s->dsi_active & 0x3fff) == f->height &&
        /* DSI_PS_Control remaps enum RGB888=2 to hardware selector5-2=3. */
        (s->dsi_ps & 0x03077fffu) == ((3u << 16) | 1152) &&
        s->dsi_vsa == 2 && s->dsi_vbp == 20 && s->dsi_vfp == 170;
}
static inline int mt6762_ovl_matches(const struct mt6762_fb_layout *f,
    const struct mt6762_ovl_snapshot *s)
{
    return f->layer <= 3 && mt6762_ovl_matches_sources(f, s, 1u << f->layer);
}
/* Exact inherited LK menu profile measured in capture9. Both memory layers
 * must be full-size BGRA within the independently reserved allocation. The
 * caller additionally validates global datapath/cache controls and renders
 * opaque pixels into layer1. This is not native display ownership. */
static inline uint64_t mt6762_boot_menu_buffer(uint64_t base, uint64_t reserved_size,
    const struct mt6762_ovl_snapshot *layers)
{
    struct mt6762_fb_layout f = {base, 0x144000, base, reserved_size, 384, 854, 1536, 1, 0};
    if (reserved_size < 2 * UINT64_C(0x144000) ||
        !mt6762_ovl_matches_sources(&f, &layers[0], 3) || layers[0].con != 0x21ff ||
        layers[0].ext_sources != 0) return 0;
    f.physical += 0x144000; f.layer = 1;
    if (!mt6762_ovl_matches_sources(&f, &layers[1], 3) || layers[1].con != 0x21ff ||
        layers[1].ext_sources != 0) return 0;
    return f.physical;
}
struct mt6762_pwm_io {
    void *context;
    uint32_t (*read)(void *, unsigned offset);
    void (*write)(void *, unsigned offset, uint32_t value);
    void (*barrier)(void *);
};
static inline int mt6762_display_datapath(uint32_t datapath, uint32_t sbch)
{
    return !sbch && (!(datapath & ~UINT32_C(0x05000009)) ||
        datapath == UINT32_C(0x81000001));
}
/* Exact LK profile measured twice in physical capture13. Preserve its 26MHz
 * source, divider0 and pin43 mux1. Duty/enable may vary through the API; all
 * configuration, shadow/commit and debug fields must retain this profile. */
struct mt6762_pwm_snapshot {
    uint32_t top, infra, gpio, enable, commit, con0, con1, debug;
};
static inline int mt6762_pwm_lk_configured(const struct mt6762_pwm_snapshot *s)
{
    return s && !(s->top & UINT32_C(0x83000000)) && !(s->infra & 4) &&
        ((s->gpio >> 12) & 15) == 1 && !(s->enable & ~1u) &&
        !s->commit && !s->con0 && !s->debug &&
        !(s->con1 & ~UINT32_C(0x1fff03ff)) &&
        (s->con1 & 1023) == 1023 && ((s->con1 >> 16) & 0x1fff) <= 1023;
}
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
