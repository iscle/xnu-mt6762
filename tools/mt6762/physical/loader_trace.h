/* SPDX-License-Identifier: MIT -- RAM-only diagnostic record, never ownership. */
#ifndef MTK_LOADER_TRACE_H
#define MTK_LOADER_TRACE_H
#include <stdint.h>
#include <stddef.h>
enum loader_phase {
    TRACE_INITIALIZED = 0, TRACE_SAFE_ENTRY = 1, TRACE_EL1 = 2,
    TRACE_C_ENTRY = 3, TRACE_IDENTITY = 4, TRACE_FDT = 5,
    TRACE_CONSOLE = 6, TRACE_WINDOW = 7, TRACE_KERNEL_COPIED = 8,
    TRACE_ARGUMENTS = 9, TRACE_JUMP_READY = 10,
    TRACE_REFUSED = 254, TRACE_EXCEPTION = 255
};
enum loader_failure {
    TRACE_BAD_CPU = 1, TRACE_BAD_FDT_POINTER = 2, TRACE_BAD_COMPATIBLE = 3,
    TRACE_BAD_MPIDR = 4, TRACE_BAD_FDT_ALIGNMENT = 5, TRACE_BAD_GIC = 6,
    TRACE_BAD_RESULT = 7, TRACE_FDT_ERROR = 0x100, TRACE_WINDOW_ERROR = 0x200
};
struct loader_trace {
    uint8_t magic[8]; uint32_t version, size; uint8_t identity[32];
    uint64_t phase, phase_inverse, sequence, sequence_inverse;
    uint64_t previous_phase, detail, original_el, fdt, midr, frequency;
    uint64_t ram, args, entry, esr, far, elr, spsr, exception_el;
    uint64_t entry_sctlr, mpidr, reserved[6];
};
_Static_assert(sizeof(struct loader_trace) == 256, "trace size");
_Static_assert(offsetof(struct loader_trace, phase) == 48, "assembly phase offset");
_Static_assert(offsetof(struct loader_trace, original_el) == 96, "assembly original EL");
_Static_assert(offsetof(struct loader_trace, esr) == 152, "assembly exception offset");
_Static_assert(offsetof(struct loader_trace, entry_sctlr) == 192, "assembly entry offset");
extern volatile struct loader_trace physical_trace;
void loader_trace_commit(uint64_t phase, uint64_t detail);
#endif
