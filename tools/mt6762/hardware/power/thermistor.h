#ifndef MT6762_THERMISTOR_H
#define MT6762_THERMISTOR_H
#include <stdint.h>
/* Nominal stock 10k NTC transfer function. Does not validate physical NTC,
 * pullup calibration, current-induced offsets, ADC freshness, or charging safety.
 * Returns 0 on success, -1 on invalid/rail/out-of-table data; keeps out unchanged. */
int mt6357_ntc_temperature(uint32_t adc_mv, uint32_t pullup_mv,
                          uint32_t pullup_ohms, int *out_deci_c);
/* Exact stock sense-path arithmetic with caller-supplied measured BIF voltage
 * and calibrated current (positive charging). com_* are the parsed numerical
 * configuration units. no_comp suppresses only com_fg, as the original does.
 * This pure function provides no freshness/calibration/ownership guarantee. */
int mt6357_ntc_compensated_temperature(uint32_t adc_mv, uint32_t bif_mv,
    uint32_t pullup_ohms, int32_t current_ua, uint32_t com_fg,
    uint32_t com_rfg, unsigned no_comp, int *out_deci_c);
#endif
