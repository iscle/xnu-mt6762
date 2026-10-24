.syntax unified
.arch armv7-a
.thumb
.section .text.entry,"ax",%progbits
.global bridge_entry
.type bridge_entry,%function
.thumb_func
bridge_entry:
    /* 56 bytes preserve incoming8-byte alignment and all original registers. */
    push.w {r0-r12,lr}
    mov r0,r7
    mov r1,r9
    bl bridge_prepare
    cmp r0,#0
    beq rejected
    pop.w {r0-r12,lr}
    ldr r12,=0x48036f39
    bx r12
rejected:
    adr r0,rejected_message
    ldr r12,=0x4801cbb9
    blx r12
    pop.w {r0-r12,lr}
    /* Original handler cleanup frees r4(header), then unwinds its own frame. */
    ldr r12,=0x4801df83
    bx r12
.balign 4
rejected_message:
    .asciz "LK cache bridge rejected download"
.balign 4
.ltorg
.size bridge_entry,.-bridge_entry
.section .note.GNU-stack,"",%progbits
