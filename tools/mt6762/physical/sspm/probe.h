/* SPDX-License-Identifier: MIT -- standalone loader diagnostic, never grants. */
#ifndef MT6762_SSPM_GUARDED_PROBE_H
#define MT6762_SSPM_GUARDED_PROBE_H
#include <stdint.h>
#include <stddef.h>

#define SSPM_PROBE_WORDS 13u
#define SSPM_PROBE_EXTERNAL_WORDS 13u
#define SSPM_PROBE_RECORD_SIZE 1024u
/* Proposed only: the integrating linker/DA reader must reserve/assert it. */
#define SSPM_PROBE_PROPOSED_RECORD_ADDRESS UINT64_C(0x40085400)
#define SSPM_PROBE_COUNTER_HZ UINT64_C(13000000)
#define SSPM_PROBE_BUDGET_TICKS UINT64_C(130000) /* dispatch checks, not bus timeout */
enum sspm_probe_state {
    SSPM_PROBE_EMPTY=0, SSPM_PROBE_RUNNING=1, SSPM_PROBE_COMPLETE=2,
    SSPM_PROBE_ABORT=3, SSPM_PROBE_REFUSED=4, SSPM_PROBE_EXPIRED=5
};
enum sspm_probe_reason {
    SSPM_PROBE_NO_REASON=0, SSPM_PROBE_BAD_ENTRY=1, SSPM_PROBE_BAD_PROFILE=2,
    SSPM_PROBE_GUARD_REJECTED=3, SSPM_PROBE_DEADLINE=4, SSPM_PROBE_TIME_REVERSED=5
};
enum sspm_probe_operation { SSPM_PROBE_IDLE=0, SSPM_PROBE_SCREEN=1, SSPM_PROBE_LOAD=2 };
enum sspm_guard_result { SSPM_GUARD_OK=0, SSPM_GUARD_ABORT=-1, SSPM_GUARD_REJECT=-2 };
struct sspm_probe_fault { uint64_t esr,far,elr,spsr; };
struct sspm_probe_word {
    uint32_t address, value[2], valid;
    uint64_t began_ticks[2], ended_ticks[2];
};
struct sspm_probe_record {
    uint8_t magic[8]; uint32_t version,size; uint8_t identity[32];
    uint32_t state,state_inverse,sequence,sequence_inverse;
    uint32_t reason,completed,index,pass,screen_count,bad_screen_word;
    uint64_t began_ticks,ended_ticks,budget_ticks,counter_hz;
    struct sspm_probe_fault fault;
    uint32_t external[SSPM_PROBE_EXTERNAL_WORDS],external_valid;
    uint64_t entry_mpidr,entry_sctlr,entry_vbar,entry_daif;
    uint32_t operation,reserved_header[3];
    struct sspm_probe_word words[SSPM_PROBE_WORDS];
    uint8_t reserved[144];
};
_Static_assert(sizeof(struct sspm_probe_record)==SSPM_PROBE_RECORD_SIZE,"record size");
_Static_assert(offsetof(struct sspm_probe_record,fault)==120,"fault offset");
_Static_assert(offsetof(struct sspm_probe_record,words)==256,"word offset");
_Static_assert(sizeof(struct sspm_probe_word)==48,"word size");
extern const uint32_t sspm_probe_addresses[SSPM_PROBE_WORDS];
extern const uint32_t sspm_probe_external_addresses[SSPM_PROBE_EXTERNAL_WORDS];

/* Assembly preserves x1..x30/NZCV, SP, DAIF/VBAR; x0 returns this result.
 * Caller is admitted EL1h, boot CPU, M/C/EE off, DAIF masked, x28 reserved0.
 * No general-address read interface; both destinations are owned Image RAM,
 * disjoint from one another, context, wrapper and future exception frames.
 * Caller must supply a valid 16-byte-aligned stack with at least 544 bytes.
 * fault is untouched on success; output is untouched on any failure. */
int sspm_guard_read(uint32_t index,uint32_t *output,volatile struct sspm_probe_fault *fault);
/* Runs only the diagnostic. Caller MUST stop afterwards, never enter XNU.
 * Record and identity must be aligned/owned Image RAM. No allocation here. */
int sspm_probe_run(volatile struct sspm_probe_record *record,const uint8_t identity[32]);
#endif
