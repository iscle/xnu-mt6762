/* SPDX-License-Identifier: MIT -- offline link fixture, never a phone Image. */
.text
.global loader_main
loader_main:
    mov x0,xzr
    ret
.global fixture_return
fixture_return:
    nop
.section .trace,"aw",%progbits
.balign 64
.global physical_trace
physical_trace:
    .zero 256
.section .sspm_fixture_record,"aw",%progbits
.balign 64
.global fixture_record
fixture_record:
    .zero 1024
.data
.balign 16
.global fixture_identity
fixture_identity:
    .ascii "SSPM-OFFLINE-FIXTURE-IDENTITY-01"
.balign 4
.global fixture_output
fixture_output:
    .word 0xa5a5a5a5
.balign 8
.global fixture_fault
fixture_fault:
    .fill 4,8,0xcccccccccccccccc
.section .note.GNU-stack,"",%progbits
