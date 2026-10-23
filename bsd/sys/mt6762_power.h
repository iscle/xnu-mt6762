#ifndef _SYS_MT6762_POWER_H_
#define _SYS_MT6762_POWER_H_
#include <stdint.h>
#define MT6762_BAT_PRESENT  (1u << 0)
#define MT6762_BAT_EXTERNAL (1u << 1)
#define MT6762_BAT_VOLTAGE  (1u << 2)
#define MT6762_BAT_CURRENT  (1u << 3)
#define MT6762_BAT_TEMP     (1u << 4)
#define MT6762_BAT_SOC      (1u << 5)
#define MT6762_BAT_STATUS   (1u << 6)
/* Every sample replaces validity; omitted values must not remain stale. */
struct mt6762_battery_sample {
    uint32_t size, valid;
    uint64_t acquired_abs, expires_abs;
    int32_t present, external, voltage_uv, current_ua;
    int32_t temperature_hundredths, percent_hundredths, status;
};
#ifdef KERNEL
#ifdef __cplusplus
extern "C" {
#endif
void mt6762_power_init(void);
int mt6762_charger_control_safe(void);
int mt6762_pwrap_read16(uint16_t address, uint16_t *value);
int mt6762_pwrap_write16(uint16_t address, uint16_t value);
int mt6762_pmic_thermal_sample(unsigned sensor,uint16_t *raw);
void mt6762_battery_report(const struct mt6762_battery_sample *sample);
uint32_t mt6762_battery_valid_fields(void);
#ifdef __cplusplus
}
#endif
#endif
#endif
