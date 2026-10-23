#ifndef MT6762_SSPM_H
#define MT6762_SSPM_H
#ifdef __cplusplus
extern "C" {
#endif
void mt6762_sspm_init(void);
/* Active PLATFORM 0xDEAD transaction, not a passive register read. */
int mt6762_sspm_probe_alive(void);
/* Passive snapshot: true only for a successful probe in the last 10 seconds.
 * This proves PLATFORM response, not initialized CPU-DVFS/thermal policy. */
int mt6762_sspm_alive_recent(void);
#ifdef __cplusplus
}
#endif
#endif
