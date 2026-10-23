#ifndef _SYS_MT6762_THERMAL_H_
#define _SYS_MT6762_THERMAL_H_
#ifdef KERNEL
void mt6762_thermal_init(void);
/* Returns0 only for fresh calibrated PMIC die/buck observations (sensor0..2).
 * CPU cached observations have no established conversion freshness proof. */
int mt6762_pmic_temperature_read(unsigned sensor,int *millicelsius);
#endif
#endif
