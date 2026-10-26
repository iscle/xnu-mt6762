/* SPDX-License-Identifier: MIT
 * Single boot CPU, EL1h, fixed-x28 loader only. No unrestricted address API.
 * All unexpected exceptions delegate to the existing physical vector slot.
 */
.arch armv8-a
.text
.balign 4
.global sspm_guard_read
.type sspm_guard_read,%function
sspm_guard_read:
    sub sp,sp,#288
    stp x0,x1,[sp,#0]
    stp x2,x3,[sp,#16]
    stp x4,x5,[sp,#32]
    stp x6,x7,[sp,#48]
    stp x8,x9,[sp,#64]
    stp x10,x11,[sp,#80]
    stp x12,x13,[sp,#96]
    stp x14,x15,[sp,#112]
    stp x16,x17,[sp,#128]
    stp x18,x19,[sp,#144]
    stp x20,x21,[sp,#160]
    stp x22,x23,[sp,#176]
    stp x24,x25,[sp,#192]
    stp x26,x27,[sp,#208]
    stp x28,x29,[sp,#224]
    str x30,[sp,#240]
    mrs x9,nzcv
    str x9,[sp,#248]
    mrs x9,CurrentEL
    cmp x9,#4
    b.ne .Lreject
    mrs x9,SPSel
    cmp x9,#1
    b.ne .Lreject
    cbnz x28,.Lreject
    mrs x9,daif
    str x9,[sp,#256]
    and x10,x9,#0x3c0
    cmp x10,#0x3c0
    b.ne .Lreject
    mrs x9,sctlr_el1
    tbnz x9,#0,.Lreject
    tbnz x9,#2,.Lreject
    tbnz x9,#25,.Lreject
    mrs x9,mpidr_el1
    tst x9,#0xffffff
    b.ne .Lreject
    ubfx x10,x9,#32,#8
    cbnz x10,.Lreject
    mrs x10,vbar_el1
    adrp x11,physical_vectors
    add x11,x11,:lo12:physical_vectors
    cmp x10,x11
    b.ne .Lreject
    str x10,[sp,#264]
    cmp x0,#13
    b.hs .Lreject
    adrp x11,image_start
    add x11,x11,:lo12:image_start
    adrp x12,image_end
    add x12,x12,:lo12:image_end
    tst x1,#3
    b.ne .Lreject
    cmp x1,x11
    b.lo .Lreject
    sub x13,x12,#4
    cmp x1,x13
    b.hi .Lreject
    tst x2,#7
    b.ne .Lreject
    cmp x2,x11
    b.lo .Lreject
    sub x13,x12,#32
    cmp x2,x13
    b.hi .Lreject
    /* Failure must leave output unchanged, including aliased destinations. */
    add x13,x1,#4
    cmp x13,x2
    b.ls .Lbuffers_disjoint
    add x13,x2,#32
    cmp x1,x13
    b.lo .Lreject
.Lbuffers_disjoint:
    /* Neither destination may overlap this wrapper OR the future exception
     * frame. A fault destination there would corrupt saved handler GPRs. */
    sub x13,sp,#256
    add x14,sp,#288
    add x15,x1,#4
    cmp x15,x13
    b.ls .Lcheck_fault_stack
    cmp x1,x14
    b.lo .Lreject
.Lcheck_fault_stack:
    add x15,x2,#32
    cmp x15,x13
    b.ls .Lcontext
    cmp x2,x14
    b.lo .Lreject
.Lcontext:
    adrp x10,sspm_guard_context
    add x10,x10,:lo12:sspm_guard_context
    add x13,x10,#64
    add x14,x1,#4
    cmp x14,x10
    b.ls .Lfault_not_context
    cmp x1,x13
    b.lo .Lreject
.Lfault_not_context:
    add x14,x2,#32
    cmp x14,x10
    b.ls .Lcontext_available
    cmp x2,x13
    b.lo .Lreject
.Lcontext_available:
    ldr x11,[x10,#0]
    cbnz x11,.Lreject
    ldr x11,[x10,#8]
    cbnz x11,.Lreject
    adrp x11,sspm_probe_addresses
    add x11,x11,:lo12:sspm_probe_addresses
    ldr w16,[x11,x0,lsl #2]
    stp x16,x0,[x10,#16]        /* expected address, whitelist index */
    stp x1,x2,[x10,#32]         /* owned output, owned fault destination */
    str x9,[x10,#48]           /* exact admitted MPIDR */
    adrp x11,sspm_probe_vectors
    add x11,x11,:lo12:sspm_probe_vectors
    msr vbar_el1,x11
    isb
    mov x11,#1
    str x11,[x10,#0]           /* armed, only once; barriers are NOT recoverable */
    dsb sy
.global sspm_guard_load
sspm_guard_load:
    ldr w17,[x16]
.global sspm_guard_after_load
sspm_guard_after_load:
    dsb sy
    str xzr,[x10,#0]
    str w17,[x1]              /* publish only after completed protected read */
    mov x0,#0
    b .Lretire
.global sspm_guard_failed
sspm_guard_failed:
    /* The vector disarms before ERET; it never changes output. */
    mov x0,#-1
.Lretire:
    str xzr,[x10,#8]
    ldr x9,[sp,#264]
    msr vbar_el1,x9
    isb
    ldr x9,[sp,#256]
    msr daif,x9
    b .Lreturn
.Lreject:
    mov x0,#-2
.Lreturn:
    str x0,[sp,#0]            /* only x0 is an ABI result; all others restored */
    ldr x9,[sp,#248]
    msr nzcv,x9
    ldp x0,x1,[sp,#0]
    ldp x2,x3,[sp,#16]
    ldp x4,x5,[sp,#32]
    ldp x6,x7,[sp,#48]
    ldp x8,x9,[sp,#64]
    ldp x10,x11,[sp,#80]
    ldp x12,x13,[sp,#96]
    ldp x14,x15,[sp,#112]
    ldp x16,x17,[sp,#128]
    ldp x18,x19,[sp,#144]
    ldp x20,x21,[sp,#160]
    ldp x22,x23,[sp,#176]
    ldp x24,x25,[sp,#192]
    ldp x26,x27,[sp,#208]
    ldp x28,x29,[sp,#224]
    ldr x30,[sp,#240]
    add sp,sp,#288
    ret
.size sspm_guard_read,.-sspm_guard_read

.balign 2048
.global sspm_probe_vectors
sspm_probe_vectors:
.set slot,0
.rept 16
    .if slot == 4
        b sspm_guard_sync
    .else
        b physical_vectors+(slot*128)
    .endif
    .space 124,0
    .set slot,slot+1
.endr

.global sspm_guard_sync
.type sspm_guard_sync,%function
sspm_guard_sync:
    /* Existing fatal handler uses x28=1 to stop recursive diagnostics.
     * Keep it set throughout our handler so a nested fault goes straight to
     * that same fatal recursion rule. The admitted original x28 was zero. */
    cbnz x28,.Lfatal_direct
    mov x28,#1
    sub sp,sp,#256
    stp x0,x1,[sp,#0]
    stp x2,x3,[sp,#16]
    stp x4,x5,[sp,#32]
    stp x6,x7,[sp,#48]
    stp x8,x9,[sp,#64]
    stp x10,x11,[sp,#80]
    stp x12,x13,[sp,#96]
    stp x14,x15,[sp,#112]
    stp x16,x17,[sp,#128]
    stp x18,x19,[sp,#144]
    stp x20,x21,[sp,#160]
    stp x22,x23,[sp,#176]
    stp x24,x25,[sp,#192]
    stp x26,x27,[sp,#208]
    stp xzr,x29,[sp,#224]
    str x30,[sp,#240]
    mrs x9,CurrentEL
    cmp x9,#4
    b.ne .Lfatal_restore
    mrs x9,SPSel
    cmp x9,#1
    b.ne .Lfatal_restore
    adrp x10,sspm_guard_context
    add x10,x10,:lo12:sspm_guard_context
    ldr x9,[x10,#0]
    cmp x9,#1
    b.ne .Lfatal_restore
    ldr x9,[x10,#8]
    cbnz x9,.Lfatal_restore
    mov x9,#1
    str x9,[x10,#8]
    mrs x9,mpidr_el1
    ldr x11,[x10,#48]
    cmp x9,x11
    b.ne .Lfatal_restore
    mrs x12,spsr_el1
    and x9,x12,#0x1f
    cmp x9,#5
    b.ne .Lfatal_restore
    and x9,x12,#0x3c0
    cmp x9,#0x3c0
    b.ne .Lfatal_restore
    mrs x13,elr_el1
    adr x9,sspm_guard_load
    cmp x13,x9
    b.ne .Lfatal_restore
    mrs x14,esr_el1
    and x9,x14,#0xfe000000
    mov x11,#0x96000000
    cmp x9,x11
    b.ne .Lfatal_restore
    mov x11,#0x5ff            /* FnV, CM, S1PTW, WnR and DFSC; EA is recorded */
    and x9,x14,x11
    cmp x9,#0x10
    b.ne .Lfatal_restore
    ldr x11,[x10,#24]
    cmp x11,#13
    b.hs .Lfatal_restore
    adrp x9,sspm_probe_addresses
    add x9,x9,:lo12:sspm_probe_addresses
    ldr w9,[x9,x11,lsl #2]
    ldr x11,[x10,#16]
    cmp x9,x11
    b.ne .Lfatal_restore
    ldr x11,[sp,#128]         /* actual address register at the faulting LDR */
    cmp x9,x11
    b.ne .Lfatal_restore
    mrs x15,far_el1
    cmp x9,x15
    b.ne .Lfatal_restore
    ldr x9,[x10,#40]
    stp x14,x15,[x9,#0]
    stp x13,x12,[x9,#16]
    str xzr,[x10,#0]          /* disarm before ERET */
    adr x9,sspm_guard_failed
    msr elr_el1,x9
    /* SPSR is intentionally unchanged: ERET restores the interrupted flags. */
    ldp x0,x1,[sp,#0]
    ldp x2,x3,[sp,#16]
    ldp x4,x5,[sp,#32]
    ldp x6,x7,[sp,#48]
    ldp x8,x9,[sp,#64]
    ldp x10,x11,[sp,#80]
    ldp x12,x13,[sp,#96]
    ldp x14,x15,[sp,#112]
    ldp x16,x17,[sp,#128]
    ldp x18,x19,[sp,#144]
    ldp x20,x21,[sp,#160]
    ldp x22,x23,[sp,#176]
    ldp x24,x25,[sp,#192]
    ldp x26,x27,[sp,#208]
    ldr x29,[sp,#232]
    ldr x30,[sp,#240]
    add sp,sp,#256
    mov x28,xzr
    eret
.Lfatal_restore:
    ldp x0,x1,[sp,#0]
    ldp x2,x3,[sp,#16]
    ldp x4,x5,[sp,#32]
    ldp x6,x7,[sp,#48]
    ldp x8,x9,[sp,#64]
    ldp x10,x11,[sp,#80]
    ldp x12,x13,[sp,#96]
    ldp x14,x15,[sp,#112]
    ldp x16,x17,[sp,#128]
    ldp x18,x19,[sp,#144]
    ldp x20,x21,[sp,#160]
    ldp x22,x23,[sp,#176]
    ldp x24,x25,[sp,#192]
    ldp x26,x27,[sp,#208]
    ldr x29,[sp,#232]
    ldr x30,[sp,#240]
    add sp,sp,#256
    mov x28,xzr
.Lfatal_direct:
    b physical_vectors+0x200
.size sspm_guard_sync,.-sspm_guard_sync

.bss
.balign 16
.global sspm_guard_context
sspm_guard_context:
    .skip 64                  /* armed,handling,address,index,output,fault,MPIDR */
.section .note.GNU-stack,"",%progbits
