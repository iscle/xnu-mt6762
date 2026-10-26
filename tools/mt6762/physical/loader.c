/* SPDX-License-Identifier: MIT
 * One-core XNU diagnostic entry. Optional native grants require live admission;
 * this loader writes no peripheral registers. Runtime FDT gates all RAM use.
 */
#include <stdint.h>
#include <stddef.h>
#include "fdt_handoff.h"
#include "payload_layout.h"
#include "loader_trace.h"
#include "diagnostic_console.h"
#include "display_probe.h"
#include "pwm_probe.h"
#include "native_display.h"
#include "native_storage.h"
#include "peripheral_probe.h"
#include "../hardware/display-touch/mt6762_touch_entry.h"
#include "../hardware/power/mt6762_pwrap_entry.h"

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
__attribute__((noreturn)) static void stop(const char *reason, uint64_t code)
{
    loader_trace_commit(TRACE_REFUSED, code);
    text("\r\nMT6762 PHYSICAL REFUSED: "); text(reason);
    text("\r\nWatchdog policy unchanged; no XNU entry.\r\n");
    for (;;) __asm__ volatile("wfe");
}
/* Assembly exception vectors pass ESR/FAR/ELR. Never resume a failed load. */
__attribute__((noreturn)) void loader_exception(uint64_t esr, uint64_t far, uint64_t elr)
{
    text("\r\nMT6762 loader exception ESR="); hex(esr);
    text(" FAR="); hex(far); text(" ELR="); hex(elr);
    physical_trace.esr = esr; physical_trace.far = far; physical_trace.elr = elr;
    loader_trace_commit(TRACE_EXCEPTION, 0);
    for (;;) __asm__ volatile("wfe");
}
/* An optional console, admitted by actual scanout readback. Tag metadata is
 * only a candidate. No register writes or native-driver ownership is granted. */
static uint32_t display_read(void *context, uint64_t address)
{ (void)context; return read32(address); }
static void display_barrier(void *context)
{ (void)context; __asm__ volatile("dsb sy" ::: "memory"); }
#if PAYLOAD_NATIVE_PWRAP_PROBE || PAYLOAD_NATIVE_MSDC_PROBE
static uint32_t pwrap_entry_read(void *context,uint32_t address)
{(void)context;return read32(address);}
#endif
#if PAYLOAD_PROBE_PERIPHERALS
static uint32_t peripheral_read(void *context,uint32_t address,unsigned width)
{
    (void)context;
    uint32_t value=width==2?*(volatile uint16_t *)(uintptr_t)address:
        *(volatile uint32_t *)(uintptr_t)address;
    __asm__ volatile("dsb sy":::"memory");return value;
}
static uint64_t peripheral_ticks(void *context)
{
    (void)context;uint64_t ticks;
    __asm__ volatile("isb; mrs %0, cntpct_el0":"=r"(ticks));return ticks;
}
#endif
static uint64_t validated_console(void)
{
    const struct display_probe_io io = {0, display_read, display_barrier};
    return display_probe_console(&fdt.framebuffer, mtk_fdt_framebuffer_reserved(&fdt),
        &io, &physical_display);
}
static void put64(unsigned char *base, size_t offset, uint64_t value)
{ memcpy(base + offset, &value, sizeof(value)); }

const struct entry_result *loader_main(uint64_t fdt_address, uint64_t original_el)
{
    uint64_t midr, frequency;
    loader_trace_commit(TRACE_C_ENTRY, 0);
    __asm__ volatile("mrs %0, midr_el1" : "=r"(midr));
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    physical_trace.midr = midr; physical_trace.frequency = frequency;
    text("\r\nMT6762 physical XNU diagnostic: EL="); hex(original_el);
    text(" MIDR="); hex(midr); text(" DTB="); hex(fdt_address); text("\r\n");
    if (((midr >> 24) & 255) != 0x41 || ((midr >> 4) & 4095) != 0xd03 || frequency != 13000000)
        stop("CPU/timer identity", TRACE_BAD_CPU);
    loader_trace_commit(TRACE_IDENTITY, 0);
    /* Exact stock header/tag allocation: 512KiB. No arbitrary pointer reads. */
    if (fdt_address != UINT64_C(0x47880000)) stop("unexpected DTB placement", TRACE_BAD_FDT_POINTER);
    int error = mtk_fdt_parse((void *)(uintptr_t)fdt_address, 0x80000, &fdt);
    if (error) stop(mtk_fdt_error_string(error), TRACE_FDT_ERROR - error);
    if (!fdt.board_compatible) stop("unsupported root compatible", TRACE_BAD_COMPATIBLE);
    loader_trace_commit(TRACE_FDT, 0);
    uint64_t framebuffer = validated_console();
    console.pixels = (void *)(uintptr_t)framebuffer;
    diagnostic_clear(&console);
    if (framebuffer) text("XNU DIAGNOSTIC\r\nBOOTLOADER DISPLAY VERIFIED\r\n");
    else text("Framebuffer unverified; UART diagnostics only\r\n");
    loader_trace_commit(TRACE_CONSOLE, 0);
    const struct display_probe_io pwm_io = {0, display_read, display_barrier};
    if (framebuffer) pwm_probe_capture(&pwm_io, &physical_pwm);
#if PAYLOAD_PROBE_PERIPHERALS
    const struct peripheral_io peripheral_io={0,peripheral_read,display_barrier,peripheral_ticks};
    peripheral_capture(&peripheral_io,&physical_peripherals);
#endif
#if PAYLOAD_NATIVE_DISPLAY
    if (!native_display_admitted(framebuffer, &physical_display, &physical_pwm))
        stop("native display/PWM profile", TRACE_BAD_NATIVE_DISPLAY);
#endif
#if PAYLOAD_NATIVE_TOUCH_PROBE
    if(!mt6762_touch_entry_ok(peripheral_read,NULL))
        stop("inherited touch bus",9);
#endif
#if PAYLOAD_REFRESH_WATCHDOG
    if(read32(0x10007000)!=0x7d || (read32(0x10007004)&0xffe0)!=0xf000 ||
       read32(0x10007030)!=0x3f0036 || read32(0x10007034)!=0x3b0034)
        stop("inherited watchdog profile",10);
#endif
#if PAYLOAD_NATIVE_PWRAP_PROBE
    if(!mt6762_pwrap_entry_ok(pwrap_entry_read,NULL))
        stop("inherited PWRAP read profile",11);
#endif
#if PAYLOAD_NATIVE_MSDC_PROBE
    struct mt6762_storage_profile storage;
    if(!mt6762_storage_profile_read(pwrap_entry_read,NULL,&storage))
        stop("inherited synchronous LK eMMC profile",12);
#endif
    struct mtk_fdt_range source = {(uintptr_t)image_start, (uintptr_t)image_end-(uintptr_t)image_start};
    uint64_t physical, memory_size=MTK_FDT_WINDOW_SIZE;
#if PAYLOAD_EXPAND_MEMORY
    uint64_t mmfr;
    __asm__ volatile("mrs %0, id_aa64mmfr0_el1":"=r"(mmfr));
    /* A53 advertises one of these architectural PA widths. Refuse newer
     * encodings rather than infer support from the amount of installed RAM. */
    static const unsigned pa_bits[]={32,36,40,42,44,48};
    if((mmfr&15)>=sizeof(pa_bits)/sizeof(pa_bits[0]))
        stop("CPU PA width",TRACE_BAD_CPU);
    error=mtk_fdt_expand_window(&fdt,fdt_address,&source,1,
        UINT64_C(1)<<pa_bits[mmfr&15],&physical,&memory_size);
#else
    error = mtk_fdt_select_window(&fdt, fdt_address, &source, 1, &physical);
#endif
    if (error) stop(mtk_fdt_error_string(error), TRACE_WINDOW_ERROR - error);
    physical_trace.ram = physical;
    loader_trace_commit(TRACE_WINDOW, 0);
    text("Validated RAM window "); hex(physical); text(" size=");hex(memory_size);
    text("; reservations="); hex(fdt.reserved_count); text("\r\n");
    for (unsigned n = 0; n < PAYLOAD_SEGMENT_COUNT; ++n) {
        const struct payload_segment *segment = &payload_segments[n];
        unsigned char *destination = (void *)(uintptr_t)(physical + segment->offset);
        memcpy(destination, xnu_blob + segment->fileoff, segment->filesize);
        memset(destination + segment->filesize, 0, segment->vmsize - segment->filesize);
    }
    loader_trace_commit(TRACE_KERNEL_COPIED, 0);
    unsigned char *adt = (void *)(uintptr_t)(physical + PAYLOAD_ADT_OFFSET);
    unsigned char *args = (void *)(uintptr_t)(physical + PAYLOAD_ARGS_OFFSET);
    memcpy((void *)(uintptr_t)(physical + PAYLOAD_RAMDISK_OFFSET), diagnostic_blob, PAYLOAD_RAMDISK_SIZE);
    memcpy(adt, adt_blob, PAYLOAD_ADT_SIZE);
    memcpy(args, args_blob, 736);
    put64(adt, PAYLOAD_ADT_DRAM_PATCH, physical);
    put64(adt, PAYLOAD_ADT_DRAM_SIZE_PATCH, memory_size);
    put64(adt, PAYLOAD_ADT_RAMDISK_PATCH, physical + PAYLOAD_RAMDISK_OFFSET);
#if PAYLOAD_NATIVE_DISPLAY
    put64(adt, PAYLOAD_ADT_FB_PHYS_PATCH, framebuffer);
    put64(adt, PAYLOAD_ADT_FB_BASE_PATCH, fdt.framebuffer.base);
    put64(adt, PAYLOAD_ADT_FB_SIZE_PATCH, fdt.framebuffer.size);
    const uint32_t granted = 1;
    for (unsigned n = 0; n < sizeof(payload_native_flags)/sizeof(payload_native_flags[0]); ++n)
        memcpy(adt + payload_native_flags[n], &granted, sizeof(granted));
#if PAYLOAD_NATIVE_TOUCH_PROBE
    for(unsigned n=0;n<sizeof(payload_touch_flags)/sizeof(payload_touch_flags[0]);n++)
        memcpy(adt+payload_touch_flags[n],&granted,sizeof(granted));
#endif
#if PAYLOAD_REFRESH_WATCHDOG
    memcpy(adt+PAYLOAD_ADT_WATCHDOG_PATCH,&granted,sizeof(granted));
#endif
#if PAYLOAD_NATIVE_PWRAP_PROBE
    for(unsigned n=0;n<sizeof(payload_pwrap_flags)/sizeof(payload_pwrap_flags[0]);n++)
        memcpy(adt+payload_pwrap_flags[n],&granted,sizeof(granted));
#endif
#if PAYLOAD_NATIVE_MSDC_PROBE
    _Static_assert(sizeof(payload_msdc_values)==sizeof(storage),"storage field/ADT patch count");
    for(unsigned n=0;n<sizeof(payload_msdc_values)/sizeof(payload_msdc_values[0]);n++)
        memcpy(adt+payload_msdc_values[n],(const unsigned char *)&storage+n*4,4);
    for(unsigned n=0;n<sizeof(payload_msdc_flags)/sizeof(payload_msdc_flags[0]);n++)
        memcpy(adt+payload_msdc_flags[n],&granted,sizeof(granted));
#endif
#endif
    put64(args, 16, physical);
    put64(args, 24, memory_size);
    put64(args, 728, memory_size);
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
    physical_trace.args = result.args; physical_trace.entry = result.entry;
    loader_trace_commit(TRACE_ARGUMENTS, 0);
    text("Entering XNU: args="); hex(result.args); text(" entry="); hex(result.entry);
#if PAYLOAD_NATIVE_DISPLAY
    text("\r\nNative display/PWM handoff admitted.\r\n");
#if PAYLOAD_NATIVE_TOUCH_PROBE
    text("Inherited I2C0 probe admitted; touch version and DMA checks required.\r\n");
#endif
#if PAYLOAD_REFRESH_WATCHDOG
    text("Inherited watchdog refresh requested; configuration preserved.\r\n");
#else
    text("Watchdog unchanged.\r\n");
#endif
#else
    text("\r\nNative peripheral ownership absent; watchdog unchanged.\r\n");
#endif
    __asm__ volatile("dsb sy\n\tic iallu\n\tdsb sy\n\tisb" ::: "memory");
    return &result;
}
