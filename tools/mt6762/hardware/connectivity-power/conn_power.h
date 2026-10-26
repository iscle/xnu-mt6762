/* SPDX-License-Identifier: MIT
 * Bounded MT6762 digital CONN cold start, ending with MCU reset held.
 * No PMIC/clock setup, EMI programming, firmware patch, DMA or radio control.
 */
#ifndef MT6762_CONN_POWER_H
#define MT6762_CONN_POWER_H
#include <stdint.h>

enum mt6762_conn_stage {
    MT6762_CONN_NONE, MT6762_CONN_COLD_ENTRY, MT6762_CONN_ASSERT_RESET,
    MT6762_CONN_POWER_ON, MT6762_CONN_POWER_ON_SECONDARY,
    MT6762_CONN_POWER_ACK, MT6762_CONN_ENABLE_CLOCK,
    MT6762_CONN_REMOVE_ISOLATION, MT6762_CONN_DOMAIN_RESET_B,
    MT6762_CONN_RELEASE_PROTECT_14_16, MT6762_CONN_RELEASE_PROTECT_13,
    MT6762_CONN_RELEASE_PROTECT1_18, MT6762_CONN_SETTLE,
    MT6762_CONN_READ_ID, MT6762_CONN_RESET_HELD_ID_VERIFIED
};
enum mt6762_conn_result {
    MT6762_CONN_OK=0, MT6762_CONN_DISABLED=1,
    MT6762_CONN_ARGUMENT=-1, MT6762_CONN_PREREQUISITE=-2,
    MT6762_CONN_IO=-3, MT6762_CONN_NOT_COLD=-4,
    MT6762_CONN_STATE_CHANGED=-5, MT6762_CONN_TIMEOUT=-6,
    MT6762_CONN_ITERATION_LIMIT=-7, MT6762_CONN_ID_MISMATCH=-8
};
struct mt6762_conn_io {
    void *context;
    int (*read32)(void *, uint32_t address, uint32_t *value);
    int (*write32)(void *, uint32_t address, uint32_t value);
    uint64_t (*ticks)(void *);
    void (*barrier)(void *); /* actual device ordering, e.g. DSB SY */
    void (*relax)(void *);   /* bounded, nonblocking, e.g. ARM YIELD */
    /* Zero only while REAL independently established prerequisites remain
     * valid under caller-held exclusive ownership. Called before each access.
     * It is not an authentication/measurement mechanism or a permission grant.
     * Caller owns PMIC, oscillator, A-die pinmux, EMI/remap+reserved memory,
     * AP mapping/access, external-LDO policy and stable timer prerequisites.
     */
    int (*prerequisites)(void *, enum mt6762_conn_stage);
    uint32_t counter_hz;            /* exactly 13000000 */
    uint32_t transition_timeout_us; /* 1..100000; proposed default 100000 */
    uint32_t total_timeout_us;      /* 1..1000000; proposed default 1000000 */
    uint32_t iteration_limit;       /* 1..10000000 per stage; includes waits */
};
/* Diagnostic values are last successful observations, never a wire record or
 * a claim that reset remains held after ownership/access is lost. There is no
 * implicit retry/rollback. Failed writes may have reached hardware. */
struct mt6762_conn_report {
    enum mt6762_conn_stage stage;
    int result, callback_error;
    uint32_t last_address, last_value;
    uint32_t last_value_valid, last_access_write;
    uint32_t reads, write_attempts, writes, prerequisite_checks, iterations;
    uint32_t reset_write_attempted, reset_observed, power_write_attempted;
    uint32_t id_valid, id;
    uint32_t snapshot[8], snapshot_valid; /* RGU, SPM, ACK0/1, EN0/ACK0, EN1/ACK1 */
    uint64_t began_ticks, ended_ticks;
};
/* enabled=0 produces DISABLED without callbacks; exactly1 executes. The caller
 * must hold ownership for the full call AND retain it on either success or
 * failure until a separate recovery/lifetime owner takes over. This function
 * never releases MCU reset and never powers anything off on error. */
int mt6762_conn_power_reset_held(const struct mt6762_conn_io *,
    struct mt6762_conn_report *, int enabled);
#endif
