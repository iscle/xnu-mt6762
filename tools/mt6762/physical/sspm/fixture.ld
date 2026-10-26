/* SPDX-License-Identifier: MIT -- test allocation only, no production linker change. */
OUTPUT_FORMAT("elf64-littleaarch64")
OUTPUT_ARCH(aarch64)
ENTRY(fixture_return)
PHDRS { image PT_LOAD FLAGS(7); }
SECTIONS {
  . = 0x40080000;
  .entry : { *(.text.entry) } :image
  . = 0x40084000;
  .trace : { *(.trace) } :image
  . = 0x40085400;
  .probe_record : { *(.sspm_fixture_record) } :image
  .text : ALIGN(2048) { *(.text .text.*) } :image
  .rodata : ALIGN(16) { *(.rodata .rodata.*) } :image
  .data : ALIGN(16) { *(.data .data.*) } :image
  .bss (NOLOAD) : ALIGN(16) {
    __bss_start = .; *(.bss .bss.* COMMON); . = ALIGN(16); __bss_end = .;
  } :image
  .stack : ALIGN(16) { __stack_start = .; *(.stack); __stack_end = .; } :image
  image_end = .;
  __image_size = image_end - image_start;
  /DISCARD/ : { *(.comment .note* .eh_frame*) }
}
ASSERT(SIZEOF(.entry) <= 0x4000, "original entry fixture overlaps trace")
ASSERT(fixture_record == 0x40085400 && SIZEOF(.probe_record) == 1024, "fixture record")
ASSERT((sspm_probe_vectors & 0x7ff) == 0, "private VBAR alignment")
ASSERT((physical_vectors & 0x7ff) == 0, "original VBAR alignment")
ASSERT((__stack_end & 15) == 0, "stack alignment")
ASSERT(__stack_end - __stack_start == 65536, "original loader stack size")
