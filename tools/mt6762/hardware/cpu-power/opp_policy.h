#ifndef MT6762_OPP_POLICY_H
#define MT6762_OPP_POLICY_H
#include <stdint.h>
enum mt6762_domain { MT6762_CPU0=0, MT6762_CPU4=1, MT6762_CCI=2 };
struct mt6762_nominal_opp { uint32_t khz, nominal_uv; uint8_t postdiv, clkdiv, index; };
/* Pure planning for stock level4 (C62). Does not authorize/program an OPP.
 * All limits must be known, nonzero; thermal_cap includes current protection.
 * Runtime EEM voltages and SSPM readiness must be resolved by integration. */
int mt6762_c62_select(enum mt6762_domain, uint32_t request_khz,
                     uint32_t policy_floor_khz, uint32_t policy_cap_khz,
                     uint32_t thermal_cap_khz, struct mt6762_nominal_opp *out);
/* Maximum shared VPROC nominal demand across both clusters and CCI. Caller
 * must supply all three indices; never lower a rail using only one domain. */
int mt6762_c62_shared_voltage(const uint8_t indices[3], uint32_t *nominal_uv);
/* PMIC linear-selector arithmetic only. Caller supplies allowed voltage window.
 * Upward rounding may not exceed maximum; output unchanged on error. */
int mt6357_selector_for_window(uint32_t minimum_uv, uint32_t maximum_uv,
                              uint8_t *selector, uint32_t *actual_uv);
/* Pure stock scheduler request encoding: no MMIO. counter must be1..255. */
int mt6762_sspm_vote(enum mt6762_domain, unsigned index, unsigned counter,
                    uint32_t *csram_offset, uint32_t *word);
#endif
