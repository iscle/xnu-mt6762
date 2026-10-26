/* Exact inherited MT6357 channel1 profile. No hardware operations or grants. */
#ifndef MT6762_VBAT_PROFILE_H
#define MT6762_VBAT_PROFILE_H
#include <stddef.h>
#include <stdint.h>
#define MT6762_VBAT_PROFILE_V1 1u
#define MT6762_VBAT_FIXED_COUNT 19u
#define MT6762_VBAT_ENTRY_COUNT 24u
static const uint16_t mt6762_vbat_entry_regs[MT6762_VBAT_ENTRY_COUNT]={
    0x0008,0x000a,0x10de,0x10e0,0x1120,0x1126,0x1128,0x112e,0x1132,0x1136,
    0x113a,0x113c,0x1008,0x11a2,0x11a4,0x11a6,0x11a8,0x11aa,0x11ac,
    0x0f8c,0x0f8e,0x0f90,0x113e,0x114c};
/* Capture44, both complete passes, checked again by producer and consumer. */
static const uint16_t mt6762_vbat_fixed_values[MT6762_VBAT_FIXED_COUNT]={
    0x5730,0x5730,0x7fca,0x000f,0x0014,0x0372,0x8083,0x4000,0x0030,0x6262,
    0x95d0,0x4055,0x0001,0x0fc0,0x0038,0x01ac,0x004c,0x0fdb,0x000d};
static inline int mt6762_vbat_entry_ok(const uint16_t *words)
{
    if(!words)return 0;
    for(unsigned i=0;i<MT6762_VBAT_FIXED_COUNT;i++)if(words[i]!=mt6762_vbat_fixed_values[i])return 0;
    /* Original preloader table @0x37fd8: F8C=AA mask3FF, F8E=0 mask1.
     * Also refuse test/interpolation-clock disable, any HK/ADC reset, RNG,
     * test/start/mux/buffer overrides and alternate output selection. These
     * are readiness predicates, not assumed uncaptured register values. */
    return (words[19]&0x3ff)==0xaa && !(words[20]&7) && !(words[21]&0xff) &&
        !(words[22]&0x3449) && !(words[23]&0x500);
}
struct mt6762_vbat_fdt_profile {uint32_t version,fdt_size,phandle,channel,ratio_num,ratio_den,avg_num;};
/* Immutable caller-owned FDT, <=512KiB. Exact paths, compatible/status,
 * provider phandle, named consumer mapping, channel/ratio/averaging required.
 * Output zero on all failures; no defaults, fixed phandle assumption or I/O. */
int mt6762_vbat_profile_from_fdt(const void *,size_t,struct mt6762_vbat_fdt_profile *);
#endif
