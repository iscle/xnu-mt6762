/* SPDX-License-Identifier: MIT
 * Temporary, one-core XNU diagnostic entry. No storage, clock, PMIC, watchdog,
 * touch or USB configuration. Runtime FDT reservations gate all RAM use.
 */
#include <stdint.h>
#include <stddef.h>
#include "fdt_handoff.h"
#include "payload_layout.h"
#include "diagnostic_console.h"
#include "../hardware/display-touch/mt6762_display_core.h"

extern unsigned char image_start[], image_end[];
extern const unsigned char xnu_blob[], diagnostic_blob[], adt_blob[], args_blob[];
struct entry_result { uint64_t args, entry; };
static struct entry_result result;
static struct mtk_fdt_info fdt;
static struct diagnostic_console console;

void *memcpy(void *to, const void *from, size_t size)
{
    unsigned char *d = to; const unsigned char *s = from;
    while (size--) *d++ = *s++;
    return to;
}
void *memset(void *to, int value, size_t size)
{
    unsigned char *d = to;
    while (size--) *d++ = (unsigned char)value;
    return to;
}
static uint32_t read32(uint64_t address)
{
    uint32_t value = *(volatile uint32_t *)(uintptr_t)address;
    __asm__ volatile("dsb sy" ::: "memory");
    return value;
}
static void uart_char(char c)
{
    diagnostic_character(&console, c);
    for (unsigned n = 0; n < 20000; ++n) {
        if (read32(0x11002014) & 32) {
            *(volatile uint32_t *)(uintptr_t)0x11002000 = (unsigned char)c;
            __asm__ volatile("dsb sy" ::: "memory");
            return;
        }
    }
}
static void text(const char *s) { while (*s) uart_char(*s++); }
static void hex(uint64_t value)
{
    text("0x");
    for (int n = 60; n >= 0; n -= 4) uart_char("0123456789abcdef"[(value >> n) & 15]);
}
__attribute__((noreturn)) static void stop(const char *reason)
{
    text("\r\nMT6762 PHYSICAL REFUSED: "); text(reason);
    text("\r\nWatchdog policy unchanged; no XNU entry.\r\n");
    for (;;) __asm__ volatile("wfe");
}
/* Assembly exception vectors pass ESR/FAR/ELR. Never resume a failed load. */
__attribute__((noreturn)) void loader_exception(uint64_t esr, uint64_t far, uint64_t elr)
{
    text("\r\nMT6762 loader exception ESR="); hex(esr);
    text(" FAR="); hex(far); text(" ELR="); hex(elr);
    stop("exception");
}
/* An optional console, admitted by actual scanout readback. Tag metadata is
 * only a candidate. No register writes or native-driver ownership is granted. */
static uint64_t validated_console(void)
{
    const struct mtk_fdt_framebuffer *tag = &fdt.framebuffer;
    if (!(tag->present & 16) || tag->found != 1) return 0;
    struct mt6762_fb_layout fb = {tag->base, 0x144000, tag->base, tag->size,
        384, 854, 1536, 1, 0};
    if (!mt6762_fb_bounds(&fb)) return 0;
    if (!mtk_fdt_framebuffer_reserved(&fdt)) return 0;
    for (unsigned pass = 0; pass < 2; ++pass) {
        if (!mt6762_display_power(read32(0x10006180), read32(0x10006184), read32(0x1000630c))) return 0;
        if (read32(0x14000100) & ((1u<<7)|(1u<<10)|(1u<<17)|(1u<<19)|(1u<<20)|(1u<<28))) return 0;
        uint32_t sources = read32(0x1400b02c);
        if (!sources || (sources & (sources-1)) || sources > 8) return 0;
        fb.layer = sources == 1 ? 0 : sources == 2 ? 1 : sources == 4 ? 2 : 3;
        uint64_t layer = fb.layer * 0x20;
        struct mt6762_ovl_snapshot s = {
            read32(0x1400b00c), sources, read32(0x1400b324), read32(0x1400b020),
            read32(0x1400b030+layer), read32(0x1400bf40+layer), read32(0x1400b044+layer),
            read32(0x1400b038+layer), read32(0x1400b03c+layer), read32(0x1400b04c+layer),
            read32(0x1400b0c0+layer), read32(0x1400d010), read32(0x14014000),
            read32(0x14014014), read32(0x14014018), read32(0x1401402c),
            read32(0x1401401c), read32(0x14014020), read32(0x14014024), read32(0x14014028)
        };
        if (!mt6762_ovl_matches(&fb, &s)) return 0;
    }
    return tag->base;
}
static void put64(unsigned char *base, size_t offset, uint64_t value)
{ memcpy(base + offset, &value, sizeof(value)); }

const struct entry_result *loader_main(uint64_t fdt_address, uint64_t original_el)
{
    uint64_t midr, frequency;
    __asm__ volatile("mrs %0, midr_el1" : "=r"(midr));
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    text("\r\nMT6762 physical XNU diagnostic: EL="); hex(original_el);
    text(" MIDR="); hex(midr); text(" DTB="); hex(fdt_address); text("\r\n");
    if (((midr >> 24) & 255) != 0x41 || ((midr >> 4) & 4095) != 0xd03 || frequency != 13000000)
        stop("CPU/timer identity");
    /* Exact stock header/tag allocation: 512KiB. No arbitrary pointer reads. */
    if (fdt_address != UINT64_C(0x47880000)) stop("unexpected DTB placement");
    int error = mtk_fdt_parse((void *)(uintptr_t)fdt_address, 0x80000, &fdt);
    if (error) stop(mtk_fdt_error_string(error));
    if (!fdt.board_compatible) stop("unsupported root compatible");
    uint64_t framebuffer = validated_console();
    console.pixels = (void *)(uintptr_t)framebuffer;
    if (framebuffer) text("XNU DIAGNOSTIC\r\nBOOTLOADER DISPLAY VERIFIED\r\n");
    else text("Framebuffer unverified; UART diagnostics only\r\n");
    struct mtk_fdt_range source = {(uintptr_t)image_start, (uintptr_t)image_end-(uintptr_t)image_start};
    uint64_t physical;
    error = mtk_fdt_select_window(&fdt, fdt_address, &source, 1, &physical);
    if (error) stop(mtk_fdt_error_string(error));
    text("Validated RAM window "); hex(physical); text(" +512MiB; reservations="); hex(fdt.reserved_count); text("\r\n");
    for (unsigned n = 0; n < PAYLOAD_SEGMENT_COUNT; ++n) {
        const struct payload_segment *segment = &payload_segments[n];
        unsigned char *destination = (void *)(uintptr_t)(physical + segment->offset);
        memcpy(destination, xnu_blob + segment->fileoff, segment->filesize);
        memset(destination + segment->filesize, 0, segment->vmsize - segment->filesize);
    }
    unsigned char *adt = (void *)(uintptr_t)(physical + PAYLOAD_ADT_OFFSET);
    unsigned char *args = (void *)(uintptr_t)(physical + PAYLOAD_ARGS_OFFSET);
    memcpy((void *)(uintptr_t)(physical + PAYLOAD_RAMDISK_OFFSET), diagnostic_blob, PAYLOAD_RAMDISK_SIZE);
    memcpy(adt, adt_blob, PAYLOAD_ADT_SIZE);
    memcpy(args, args_blob, 736);
    put64(adt, PAYLOAD_ADT_DRAM_PATCH, physical);
    put64(adt, PAYLOAD_ADT_RAMDISK_PATCH, physical + PAYLOAD_RAMDISK_OFFSET);
    put64(args, 16, physical);
    put64(args, 32, physical + PAYLOAD_TOP_OFFSET);
    if (framebuffer) {
        args[PAYLOAD_SERIAL_PATCH] = '0'; /* Keep /dev/console on verified video. */
        put64(args, 40, framebuffer | 1); /* Physical mapping, text mode. */
        put64(args, 48, 0); put64(args, 56, 1536);
        put64(args, 64, 384); put64(args, 72, 854); put64(args, 80, 32);
        text("Verified inherited framebuffer; text console requested\r\n");
    }
    result.args = physical + PAYLOAD_ARGS_OFFSET;
    result.entry = physical + PAYLOAD_ENTRY_OFFSET;
    text("Entering XNU: args="); hex(result.args); text(" entry="); hex(result.entry);
    text("\r\nNative peripheral ownership absent; watchdog unchanged.\r\n");
    __asm__ volatile("dsb sy\n\tic iallu\n\tdsb sy\n\tisb" ::: "memory");
    return &result;
}
