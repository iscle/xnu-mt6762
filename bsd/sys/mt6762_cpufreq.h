#ifndef MT6762_CPUFREQ_H
#define MT6762_CPUFREQ_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void mt6762_cpufreq_init(void);
/* Readback-only attachment. No performance request or voltage-write API yet. */
#ifdef __cplusplus
}
#endif
#endif
