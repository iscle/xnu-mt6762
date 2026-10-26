/* Fixed LK destination. All output storage is present in the raw Image. */
OUTPUT_FORMAT("elf64-littleaarch64")
OUTPUT_ARCH(aarch64)
ENTRY(_start)
PHDRS { image PT_LOAD FLAGS(7); }
SECTIONS
{
    . = 0x40080000;
    .entry : ALIGN(8) {
        KEEP(*(.text.entry))
    } :image
    . = 0x40084000;
    .trace : ALIGN(64) {
        KEEP(*(.trace))
    } :image
    .display_trace : ALIGN(64) {
        KEEP(*(.display_trace))
    } :image
    .pwm_trace : ALIGN(64) {
        KEEP(*(.pwm_trace))
    } :image
    .peripheral_trace : ALIGN(64) {
        KEEP(*(.peripheral_trace))
    } :image
    .text : ALIGN(8) {
        *(.text .text.*)
    } :image
    .rodata : ALIGN(16) {
        *(.rodata .rodata.*)
    } :image
    .data : ALIGN(16) {
        *(.data .data.*)
        *(.sdata .sdata.*)
    } :image
    .payload : ALIGN(16) {
        __payload_start = .;
        KEEP(*(.payload .payload.*))
        __payload_end = .;
    } :image
    /* lld rejects casting NOBITS inputs to PROGBITS. The following PROGBITS
     * stack forces these bytes into the single segment's file extent and
     * raw Image as a zero-filled gap; entry explicitly zeroes them as well. */
    .bss (NOLOAD) : ALIGN(16) {
        __bss_start = .;
        *(.bss .bss.* .sbss .sbss.* COMMON)
        . = ALIGN(16);
        __bss_end = .;
    } :image
    .stack : ALIGN(16) {
        __stack_start = .;
        KEEP(*(.stack))
        . = ALIGN(16);
        __stack_end = .;
    } :image
    . = ALIGN(16);
    image_end = .;
    __image_size = image_end - image_start;
    /DISCARD/ : { *(.comment .note* .eh_frame .eh_frame_hdr .ARM.attributes) }
}
ASSERT(_start == 0x40080000, "physical entry load address changed")
ASSERT(image_start == _start, "Linux Image header is not first")
ASSERT(SIZEOF(.entry) <= 0x4000, "entry overlaps fixed trace record")
ASSERT(physical_trace == 0x40084000 && SIZEOF(.trace) == 256, "fixed trace layout")
ASSERT(physical_display == 0x40084100 && SIZEOF(.display_trace) == 512, "fixed display record layout")
ASSERT(physical_pwm == 0x40084300 && SIZEOF(.pwm_trace) == 256, "fixed PWM record layout")
ASSERT(physical_peripherals == 0x40084400 && SIZEOF(.peripheral_trace) == 4096, "fixed peripheral record layout")
ASSERT(physical_peripherals + SIZEOF(.peripheral_trace) <= 0x40090000, "peripheral record outside reserved DA prefix")
ASSERT(physical_pwm + SIZEOF(.pwm_trace) <= 0x40090000, "PWM record outside reserved DA prefix")
ASSERT(physical_display + SIZEOF(.display_trace) <= 0x40090000, "display record outside reserved DA prefix")
ASSERT(physical_trace + SIZEOF(.trace) <= 0x40200000, "trace outside bounded source-image read range")
ASSERT((physical_vectors & 0x7ff) == 0, "VBAR alignment")
ASSERT((__bss_start & 15) == 0 && (__bss_end & 15) == 0, "BSS zero alignment")
ASSERT(__stack_end - __stack_start == 65536, "private stack must be64KiB")
ASSERT(image_end <= 0x47880000, "Image overlaps stock tags/FDT or exceeds120MiB")
