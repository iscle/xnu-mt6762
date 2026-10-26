/* SPDX-License-Identifier: MIT
 * Conditional UI estimate only. Never use as charger/protection input. */
#ifndef MT6762_BATTERY_SOC_H
#define MT6762_BATTERY_SOC_H
#include <stddef.h>
#include <stdint.h>
#define BS_TABLES 6U
#define BS_ROWS 74U
#define BS_PROFILE_BYTES (BS_ROWS * 12U)
#define BS_MODEL_CAPACITY_UAH INT64_C(2200000)
#define BS_MAX_LEASE_US UINT64_C(2000000)
#define BS_MAX_GAP_US UINT64_C(5000000)
#define BS_MAX_CURRENT_UA 2000000
/* Exact-stock0.1mAh output quantization; two endpoints can differ by one
 * quantum each. This tolerance is arithmetic, not a physical accuracy bound. */
#define BS_CAR_TOLERANCE_UAH INT64_C(200)
enum bs_error { BS_OK=0, BS_PENDING=1, BS_ARGUMENT=-1, BS_PROFILE=-2,
    BS_DISABLED=-3, BS_STALE=-4, BS_TIME=-5, BS_COUNTER=-6,
    BS_JUMP=-7, BS_DIRECTION=-8, BS_RANGE=-9, BS_FAULT=-10 };
enum bs_state_kind { BS_OFF, BS_WAIT_FIRST, BS_WAIT_SECOND, BS_TRACKING, BS_FAILED };
enum bs_quality { BS_ESTIMATED=1, BS_TEMPERATURE_UNKNOWN=2,
    BS_CONDITIONAL_IR_MODEL=4, BS_NONMONOTONIC_PROFILE=8,
    BS_ENDPOINT_CAPACITY_MODEL=16, BS_NOT_PHYSICAL_CONFIDENCE_INTERVAL=32 };
struct bs_blob { const unsigned char *bytes; size_t length; };
struct bs_coefficients { uint32_t rfg_dt, car_tune_dt, meter_resistance_dt; };
struct bs_row { uint32_t charge_0p1mah, voltage_0p1mv, resistance_0p1mohm; };
/* Only bs_profile_init output may be supplied to other APIs; keep immutable
 * afterwards. Marker is a programming invariant, NOT an authenticity token. */
struct bs_profile {
    uint32_t initialized;
    struct bs_row rows[BS_TABLES][BS_ROWS];
    uint32_t resistance_min_0p1mohm, resistance_max_0p1mohm;
};
struct bs_sample {
    /* One immutable coherent observer snapshot: lease starts before any I/O.
     * Times are monotonic microseconds; no time conversion inside this core. */
    uint64_t acquired_us, expires_us, sequence, nter_ticks, generation;
    int64_t charge_uah; /* arbitrary inherited origin; positive charge */
    int32_t current_ua; /* positive charge */
    uint32_t voltage_uv;
    uint32_t valid; /* must equal7: fresh VBAT,current,CAR; no unknown bits */
};
struct bs_result {
    uint32_t valid, quality;
    uint32_t lower_bp, upper_bp; /* basis points:10000 means100%; no midpoint */
    int64_t conditional_ocv_lower_uv, conditional_ocv_upper_uv;
    uint64_t acquired_us, expires_us, ocv_acquired_us;
};
struct bs_state {
    uint32_t phase; int32_t fault;
    uint64_t last_now_us;
    struct bs_sample previous;
    int64_t seed_charge_uah;
    uint32_t seed_lower_bp, seed_upper_bp;
    struct bs_result last;
};
/* BE triples plus exact observed num=100/col=3 and temperatures. Hashes pin all
 * six shipped payloads, including their anomalies; no profile data embedded. */
int bs_profile_init(struct bs_profile *, const struct bs_blob[BS_TABLES],
    const uint32_t declared_rows[BS_TABLES], const uint32_t columns[BS_TABLES],
    const int32_t temperatures_c[BS_TABLES], const struct bs_coefficients *);
/* Input voltage is a CONDITIONAL OCV interval; examines every segment in all
 * six profiles, retaining ambiguities. No physical freshness/permission claim. */
int bs_ocv_interval(const struct bs_profile *, int64_t lower_uv, int64_t upper_uv,
    struct bs_result *);
/* enabled must be1 and explicitly opts into endpoint/IR assumptions described
 * in README. No automatic restart or reseeding after invalidation. */
int bs_begin(struct bs_state *, unsigned enabled);
int bs_update(struct bs_state *, const struct bs_profile *, const struct bs_sample *,
    uint64_t now_us, struct bs_result *);
/* Poll expiry even when acquisition stops. Expiry is terminal until explicit
 * new bs_begin, so a stale cached percentage cannot quietly persist. */
int bs_read(struct bs_state *, uint64_t now_us, struct bs_result *);
#endif
