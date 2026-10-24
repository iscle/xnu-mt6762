/* Physical MT6762 entry: Linux arm64 Image convention, not a QEMU loader.
 * LK supplies x0=FDT. No stack/data writes occur until entry-state admission.
 * CPU/system-register setup follows the supplied Linux4.9 arm64 head.S.
 */
.arch armv8-a
.section .text.entry, "ax", %progbits
.balign 8
.global _start
.global image_start
.type _start, %function
_start:
image_start:
    b       physical_entry
    .word   0
    .quad   0x80000                 /* text_offset from aligned DRAM base */
    .quad   __image_size            /* includes payload, zero storage, stack */
    .quad   0x0a                   /* LE, 4KiB pages, physical placement */
    .quad   0
    .quad   0
    .quad   0
    .word   0x644d5241             /* ARM\x64 */
    .word   0

physical_entry:
    msr     daifset, #0xf
    mov     x19, x0                /* original firmware FDT */
    mrs     x20, CurrentEL
    lsr     x20, x20, #2           /* original EL as numeric1/2 */
    mov     x28, xzr               /* fatal-vector recursion guard */
    cmp     x20, #1
    b.eq    .Ladmit_el1
    cmp     x20, #2
    b.ne    physical_halt
    mrs     x9, sctlr_el2
    b       .Ladmit_state
.Ladmit_el1:
    mrs     x9, sctlr_el1
.Ladmit_state:
    tbnz    x9, #0, physical_halt  /* MMU must already be off */
    tbnz    x9, #2, physical_halt  /* data cache must already be off */
    tbnz    x9, #25, physical_halt /* big-endian entry is unsupported */
    mrs     x10, mpidr_el1
    tst     x10, #0xffff           /* only boot CPU Aff1=0/Aff0=0 */
    b.ne    physical_halt
    cbz     x19, physical_halt
    tst     x19, #7
    b.ne    physical_halt

    /* From here memory is addressed physically, with validated LE state. */
    msr     spsel, #1
    adrp    x10, physical_vectors
    add     x10, x10, :lo12:physical_vectors
    msr     vbar_el1, x10
    bic     x9, x9, #(1 << 12)     /* leave instruction cache off too */
    cmp     x20, #2
    b.eq    .Lprepare_el2
    msr     sctlr_el1, x9
    isb
    b       .Lentry_el1

.Lprepare_el2:
    msr     vbar_el2, x10
    msr     sctlr_el2, x9
    isb
    mov     x9, #(1 << 31)         /* HCR.RW=1, no stage2/VHE */
    msr     hcr_el2, x9
    isb
    mrs     x9, cnthctl_el2
    orr     x9, x9, #3             /* EL1 physical timer/counter access */
    msr     cnthctl_el2, x9
    msr     cntvoff_el2, xzr

    mrs     x9, id_aa64pfr0_el1
    ubfx    x9, x9, #24, #4
    cbz     x9, .Lgic_done
    mrs     x9, S3_4_C12_C9_5      /* ICC_SRE_EL2 */
    orr     x9, x9, #1
    orr     x9, x9, #8
    msr     S3_4_C12_C9_5, x9
    isb
    mrs     x9, S3_4_C12_C9_5
    tbz     x9, #0, physical_halt
    msr     S3_4_C12_C11_0, xzr    /* ICH_HCR_EL2 */
.Lgic_done:
    mrs     x9, midr_el1
    msr     vpidr_el2, x9
    mrs     x9, mpidr_el1
    msr     vmpidr_el2, x9
    mov     x9, #0x0800
    movk    x9, #0x30d0, lsl #16
    msr     sctlr_el1, x9          /* LE, architected RES1, M/C/I off */
    mov     x9, #0x33ff
    msr     cptr_el2, x9
    msr     hstr_el2, xzr
    mrs     x9, id_aa64dfr0_el1
    sbfx    x9, x9, #8, #4
    cmp     x9, #1
    b.lt    .Lno_pmu
    mrs     x9, pmcr_el0
    ubfx    x9, x9, #11, #5
    b       .Lset_mdcr
.Lno_pmu:
    mov     x9, xzr
.Lset_mdcr:
    msr     mdcr_el2, x9
    msr     vttbr_el2, xzr
    adrp    x9, __stack_end
    add     x9, x9, :lo12:__stack_end
    msr     sp_el1, x9
    adr     x9, .Lentry_el1
    msr     elr_el2, x9
    mov     x9, #0x3c5             /* DAIF masked, EL1h */
    msr     spsr_el2, x9
    isb
    eret

.Lentry_el1:
    /* EL1 entry leaves EL2/GZ timer offsets and hypervisor state untouched. */
    adrp    x9, __stack_end
    add     x9, x9, :lo12:__stack_end
    mov     sp, x9
    mov     x29, xzr
    adrp    x9, __bss_start
    add     x9, x9, :lo12:__bss_start
    adrp    x10, __bss_end
    add     x10, x10, :lo12:__bss_end
.Lzero_bss:
    cmp     x9, x10
    b.hs    .Lbss_done
    stp     xzr, xzr, [x9], #16
    b       .Lzero_bss
.Lbss_done:
    dsb     sy
    ic      iallu
    dsb     sy
    isb
    mov     x0, x19
    mov     x1, x20
    bl      loader_main
    cbz     x0, physical_halt
    tst     x0, #7
    b.ne    physical_halt
    ldp     x9, x16, [x0]          /* {boot_args physical pointer, entry} */
    cbz     x9, physical_halt
    tst     x9, #7
    b.ne    physical_halt
    cbz     x16, physical_halt
    tst     x16, #3
    b.ne    physical_halt
    dsb     sy
    ic      iallu
    dsb     sy
    isb
    mov     x0, x9
    mov     x1, xzr
    mov     x2, xzr
    mov     x3, xzr
    br      x16
.size _start, . - _start

/* No stack accesses in exception paths. A UART abort re-enters with x28=1
 * and immediately halts instead of recursively attempting another diagnostic.
 * Only inherited UART0 THR/LSR are accessed; no clock, reset or baud changes.
 */
.balign 2048
.global physical_vectors
physical_vectors:
.rept 16
    b       physical_exception
    .space  124, 0
.endr

physical_exception:
    msr     daifset, #0xf
    cbnz    x28, physical_halt
    mov     x28, #1
    mrs     x23, CurrentEL
    cmp     x23, #8
    b.eq    .Lesr_el2
    mrs     x25, esr_el1
    b       .Lprint_esr
.Lesr_el2:
    mrs     x25, esr_el2
.Lprint_esr:
    mov     w0, #'!'
    bl      .Luart_character
    lsr     x23, x23, #2
    add     w0, w23, #'0'
    bl      .Luart_character
    mov     w0, #':'
    bl      .Luart_character
    mov     x24, #28
.Lhex_digit:
    lsr     x0, x25, x24
    and     w0, w0, #15
    cmp     w0, #9
    add     w9, w0, #'0'
    add     w0, w0, #('a' - 10)
    csel    w0, w9, w0, ls
    bl      .Luart_character
    subs    x24, x24, #4
    b.ge    .Lhex_digit
    mov     w0, #10
    bl      .Luart_character
    b       physical_halt

.Luart_character:
    mov     x9, #0x2000
    movk    x9, #0x1100, lsl #16   /* MTK UART0, 32-bit register spacing */
    mov     x10, #65536
.Luart_wait:
    ldr     w11, [x9, #0x14]       /* LSR.THRE */
    tbnz    w11, #5, .Luart_write
    subs    x10, x10, #1
    b.ne    .Luart_wait
    ret
.Luart_write:
    str     w0, [x9]
    dsb     sy
    ret

.global physical_halt
physical_halt:
    msr     daifset, #0xf
.Lhalt:
    wfe
    b       .Lhalt

.section .stack, "aw", %progbits
.balign 16
    .space  65536, 0

.section .note.GNU-stack, "", %progbits
