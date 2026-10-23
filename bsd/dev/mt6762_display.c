/* SPDX-License-Identifier: MIT
 * Preserve a verified running OVL0/DSI scanout, and update its inherited PWM.
 * Does not start a panel or alter clocks, bias rails, reset, DMA translation.
 */
#include <kern/locks.h>
#include <libkern/libkern.h>
#include <vm/pmap.h>
#include <pexpert/device_tree.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_display.h>
#include "../../tools/mt6762/hardware/display-touch/mt6762_display_core.h"
extern uint64_t kvtophys(vm_offset_t);

static struct mt6762_fb_layout display;
static volatile uint32_t *spm, *mmsys, *ovl, *rdma, *dsi, *pwm, *top, *infra;
static int display_ready, brightness_ready;
static LCK_GRP_DECLARE(display_group, "mt6762-display");
static LCK_MTX_DECLARE(display_lock, &display_group);
static uint32_t read32(volatile uint32_t *base, unsigned offset)
{
    uint32_t value = base[offset / 4];
    __asm__ volatile("dsb oshld" ::: "memory");
    return value;
}
static int property(const char *name, uint32_t expected)
{
    uint32_t value;
    return !mt6762_handoff_u32(name, &value) && value == expected;
}
static int power_on(void)
{
    return mt6762_display_power(read32(spm, 0x180), read32(spm, 0x184), read32(spm, 0x30c));
}
static int scanout_matches(void)
{
    if (!power_on()) return 0;
    /* Check gates before reading the display engines. */
    if (read32(mmsys, 0x100) & ((1u << 7) | (1u << 10) | (1u << 17) |
        (1u << 19) | (1u << 20) | (1u << 28))) return 0;
    unsigned layer = display.layer * 0x20;
    struct mt6762_ovl_snapshot s = {
        .en = read32(ovl, 0x00c), .sources = read32(ovl, 0x02c),
        .ext_sources = read32(ovl, 0x324), .roi = read32(ovl, 0x020),
        .con = read32(ovl, 0x030 + layer), .address = read32(ovl, 0xf40 + layer),
        .pitch = read32(ovl, 0x044 + layer), .size = read32(ovl, 0x038 + layer),
        .offset = read32(ovl, 0x03c + layer), .clip = read32(ovl, 0x04c + layer),
        .rdma = read32(ovl, 0x0c0 + layer), .downstream_rdma = read32(rdma, 0x010),
        .dsi_start = read32(dsi, 0), .dsi_mode = read32(dsi, 0x014),
        .dsi_lanes = read32(dsi, 0x018), .dsi_active = read32(dsi, 0x02c),
        .dsi_ps = read32(dsi, 0x01c), .dsi_vsa = read32(dsi, 0x020),
        .dsi_vbp = read32(dsi, 0x024), .dsi_vfp = read32(dsi, 0x028)
    };
    return mt6762_ovl_matches(&display, &s);
}
static int pwm_configured(void)
{
    if (!power_on()) return 0;
    uint32_t top_config = read32(top, 0x80), infra_config = read32(infra, 0xac);
    if ((top_config & 0x80000000u) || (infra_config & 4)) return 0;
    return mt6762_pwm_configured(read32(pwm, 0x18), read32(pwm, 0x1c), top_config, infra_config);
}
static void display_init_locked(void)
{
    if (display_ready) return;
    if (!mt6762_platform_ready() || !property("display-verified", 1) ||
        !property("display-reserved", 1) || !property("display-dma-physical", 1) ||
        !property("display-pipeline-verified", 1)) {
        printf("mt6762-display: unavailable: verified scanout/reservation/DMA handoff required\n");
        return;
    }
    if (mt6762_handoff_u64("fb-phys", &display.physical) ||
        mt6762_handoff_u64("fb-size", &display.size) ||
        mt6762_handoff_u64("fb-reserved-base", &display.reserved_base) ||
        mt6762_handoff_u64("fb-reserved-size", &display.reserved_size) ||
        mt6762_handoff_u32("fb-width", &display.width) ||
        mt6762_handoff_u32("fb-height", &display.height) ||
        mt6762_handoff_u32("fb-stride", &display.stride) ||
        mt6762_handoff_u32("fb-format", &display.format) ||
        mt6762_handoff_u32("fb-ovl-layer", &display.layer) || !mt6762_fb_bounds(&display)) {
        printf("mt6762-display: unavailable: framebuffer layout/bounds rejected\n");
        return;
    }
    spm = mt6762_map_mmio(0x10006000, 0x1000);
    mmsys = mt6762_map_mmio(0x14000000, 0x1000);
    ovl = mt6762_map_mmio(0x1400b000, 0x1000);
    rdma = mt6762_map_mmio(0x1400d000, 0x1000);
    dsi = mt6762_map_mmio(0x14014000, 0x1000);
    if (!spm || !mmsys || !ovl || !rdma || !dsi || !scanout_matches()) {
        printf("mt6762-display: unavailable: power/clocks/OVL0/DSI readback mismatch\n");
        return;
    }
    /* Early PE initialization suppressed Video for all native handoffs.
     * Use the official physical-console mapping path only after validation,
     * with its IO/write-combined attributes. No guessed virtual alias. */
    PE_Video video = {0};
    video.v_baseAddr = (unsigned long)display.physical | 1;
    video.v_width = display.width; video.v_height = display.height;
    video.v_rowBytes = display.stride; video.v_depth = 32;
    video.v_length = (unsigned long)display.stride * display.height;
    video.v_display = 1; video.v_scale = kPEScaleFactor1x;
    strlcpy(video.v_pixelFormat, "BBBBBBBBGGGGGGGGRRRRRRRR", sizeof(video.v_pixelFormat));
    /* kPEEnableScreen copies into PE_state, which is read-only after IOKit
     * lockdown. GraphicsMode updates the mutable console mapping only. */
    PE_initialize_console(&video, kPEGraphicsMode);
    display_ready = 1;
    printf("mt6762-display: inherited OVL0 layer %u, 384x854 BGRA scanout verified; no panel reset\n", display.layer);
    if (!property("brightness-verified", 1) || !property("brightness-pins-verified", 1) ||
        !property("brightness-parent-verified", 1)) {
        printf("mt6762-brightness: unavailable: verified output/parent handoff required\n");
        return;
    }
    top = mt6762_map_mmio(0x10000000, 0x1000);
    infra = mt6762_map_mmio(0x10001000, 0x1000);
    pwm = mt6762_map_mmio(0x1100e000, 0x1000);
    if (!top || !infra || !pwm || !pwm_configured()) {
        printf("mt6762-brightness: unavailable: PWM parent/divider/period/gate mismatch\n");
        return;
    }
    brightness_ready = 1;
    printf("mt6762-brightness: inherited DISP_PWM0 validated; explicit duty API available\n");
}
void mt6762_display_init(void)
{
    lck_mtx_lock(&display_lock);
    display_init_locked();
    lck_mtx_unlock(&display_lock);
}
static int display_usable_locked(uintptr_t virtual_base, unsigned width, unsigned height,
    unsigned stride, unsigned depth)
{
    DTEntry entry;
    /* Cached platform handoff may not have been initialized yet. Any native
     * handoff node, including a malformed one, must fail closed here. */
    if (SecureDTLookupEntry(NULL, "/chosen/mt6762-handoff", &entry) != kSuccess) return 1;
    if (!display_ready || !virtual_base || width != display.width || height != display.height ||
        stride != display.stride || depth != 32 || !scanout_matches()) return 0;
    uint64_t bytes = (uint64_t)stride * height;
    if (bytes > UINTPTR_MAX - virtual_base) return 0;
    /* Check each hardware page, including the last byte: no assumed linear
     * relationship between the kernel virtual console and physical scanout. */
    for (uint64_t offset = 0; offset < bytes; offset += 4096)
        if (kvtophys((vm_offset_t)(virtual_base + offset)) != display.physical + offset) return 0;
    return kvtophys((vm_offset_t)(virtual_base + bytes - 1)) == display.physical + bytes - 1;
}
int mt6762_display_usable(uintptr_t virtual_base, unsigned width, unsigned height,
    unsigned stride, unsigned depth)
{
    lck_mtx_lock(&display_lock);
    int usable = display_usable_locked(virtual_base, width, height, stride, depth);
    lck_mtx_unlock(&display_lock);
    return usable;
}
static uint32_t pwm_read(void *unused, unsigned offset)
{
    (void)unused; return read32(pwm, offset);
}
static void pwm_write(void *unused, unsigned offset, uint32_t value)
{
    (void)unused; pwm[offset / 4] = value;
}
static void pwm_barrier(void *unused)
{
    (void)unused; __asm__ volatile("dsb osh" ::: "memory");
}
int mt6762_brightness_set(unsigned level)
{
    const struct mt6762_pwm_io io = {NULL, pwm_read, pwm_write, pwm_barrier};
    int error = -1;
    lck_mtx_lock(&display_lock);
    if (level <= 1023 && brightness_ready && pwm_configured()) {
        error = mt6762_pwm_program(&io, level);
        if (error) brightness_ready = 0;
    } else if (brightness_ready) {
        /* Never resume after loss of inherited clock/power ownership. */
        if (level <= 1023) brightness_ready = 0;
    }
    lck_mtx_unlock(&display_lock);
    return error;
}
int mt6762_brightness_get(unsigned *level)
{
    if (!level) return -1;
    int error = -1;
    lck_mtx_lock(&display_lock);
    if (brightness_ready && pwm_configured()) {
        unsigned duty = (read32(pwm, 0x1c) >> 16) & 0x1fff;
        if (duty <= 1023) {
            *level = (read32(pwm, 0) & 1) ? duty : 0;
            error = 0;
        }
    }
    if (error && brightness_ready) brightness_ready = 0;
    lck_mtx_unlock(&display_lock);
    return error;
}
