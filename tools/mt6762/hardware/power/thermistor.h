#ifndef MT6762_THERMISTOR_H
#define MT6762_THERMISTOR_H
#include <stdint.h>
/* Nominal stock 10k NTC transfer function. Does not validate physical NTC,
 * pullup calibration, current-induced offsets, ADC freshness, or charging safety.
 * Returns 0 on success, -1 on invalid/rail/out-of-table data; keeps out unchanged. */
int mt6357_ntc_temperature(uint32_t adc_mv, uint32_t pullup_mv,
                          uint32_t pullup_ohms, int *out_deci_c);
#endif
