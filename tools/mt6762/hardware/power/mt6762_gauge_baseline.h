/* SPDX-License-Identifier: MIT -- exact-stock fresh-boot coefficient profile.
 * Pure validation of caller-owned immutable FDT bytes; no hardware access.
 * This is not the last Android runtime value, a hardware calibration check,
 * or an ownership grant. See GAUGE-BASELINE.rst for source and replay evidence.
 */
#ifndef MT6762_GAUGE_BASELINE_H
#define MT6762_GAUGE_BASELINE_H
#include <stddef.h>
#include <stdint.h>
#define MT6762_GAUGE_BASELINE_V1 1u
#define MT6762_GAUGE_BASELINE_MAX_FDT 0x80000u
struct mt6762_gauge_baseline {
    uint32_t version,fdt_size;
    uint32_t dt_r_fg,dt_car_tune;
    uint32_t r_fg,car_tune;
};
enum mt6762_gauge_baseline_error {
    MT6762_GAUGE_BASELINE_E_HEADER=-1,
    MT6762_GAUGE_BASELINE_E_BOUNDS=-2,
    MT6762_GAUGE_BASELINE_E_STRUCTURE=-3,
    MT6762_GAUGE_BASELINE_E_AMBIGUOUS=-4,
    MT6762_GAUGE_BASELINE_E_PROFILE=-5,
    MT6762_GAUGE_BASELINE_E_DISABLED=-6,
    MT6762_GAUGE_BASELINE_E_LIMIT=-7
};
/* On any error *out is zeroed. A successful result is only a reproducible
 * fresh initialization coefficient pair (100,1000), derived from present
 * DT cells (10,100) by the exact stock multiplier10. No default fallback.
 * Does not change existing mtk_fdt_info or depend on its layout. The caller
 * must separately validate hardware calibration shadows, clocks/latch state,
 * exclusive ownership, and fresh coherent acquisition before measurement. */
int mt6762_gauge_baseline_from_fdt(const void *blob,size_t accessible,
    struct mt6762_gauge_baseline *out);
#endif
