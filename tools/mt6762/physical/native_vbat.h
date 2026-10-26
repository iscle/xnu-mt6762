/* SPDX-License-Identifier: MIT
 * Loader-only ADC profile admission. Callbacks may issue PMIC reads only.
 * Does not start conversion, alter calibration or grant broad PMIC writes.
 */
#ifndef MT6762_NATIVE_VBAT_H
#define MT6762_NATIVE_VBAT_H
#include "../hardware/power/mt6762_vbat_profile.h"

struct mt6762_vbat_entry_io {
    void *context;
    int (*read)(void *,uint16_t,uint16_t *);
    uint64_t (*ticks)(void *);
};
#define MT6762_VBAT_ADMISSION_TICKS UINT64_C(1300000) /*100ms at13MHz*/
enum mt6762_vbat_admission_status {
    VBAT_ADMIT_UNAVAILABLE,VBAT_ADMIT_OK,VBAT_ADMIT_FDT,VBAT_ADMIT_TIME,
    VBAT_ADMIT_TRANSPORT,VBAT_ADMIT_PROFILE,VBAT_ADMIT_CHANGED,VBAT_ADMIT_TIMER_STUCK
};
struct mt6762_vbat_entry_report {
    uint32_t status,reads,reuse_word,reuse_passes;
};

static int mt6762_vbat_admit(const void *fdt,size_t size,
    const struct mt6762_vbat_entry_io *io,uint32_t values[6],
    struct mt6762_vbat_entry_report *report)
{
    if(!values)return 0;
    for(unsigned i=0;i<6;i++)values[i]=0;
    if(!report)return 0;
    *report=(struct mt6762_vbat_entry_report){0};
    if(!io || !io->read || !io->ticks)return 0;
    struct mt6762_vbat_fdt_profile profile;
    report->status=VBAT_ADMIT_FDT;
    if(mt6762_vbat_profile_from_fdt(fdt,size,&profile))return 0;
    uint16_t first[MT6762_VBAT_ENTRY_COUNT],second[MT6762_VBAT_ENTRY_COUNT];
    uint64_t start=io->ticks(io->context),last=start;
    for(unsigned pass=0;pass<2;pass++) {
        uint16_t *words=pass?second:first;
        for(unsigned i=0;i<MT6762_VBAT_ENTRY_COUNT;i++) {
            uint64_t now=io->ticks(io->context);
            report->status=VBAT_ADMIT_TIME;
            if(now<last || now-start>MT6762_VBAT_ADMISSION_TICKS)return 0;
            last=now;
            report->status=VBAT_ADMIT_TRANSPORT;
            if(io->read(io->context,mt6762_vbat_entry_regs[i],&words[i]))return 0;
            report->reads++;
            if(mt6762_vbat_entry_regs[i]==0x114c) {
                report->reuse_word=words[i];report->reuse_passes|=1u<<pass;
            }
            now=io->ticks(io->context);
            report->status=VBAT_ADMIT_TIME;
            if(now<last || now-start>MT6762_VBAT_ADMISSION_TICKS)return 0;
            last=now;
            report->status=VBAT_ADMIT_CHANGED;
            if(pass && first[i]!=second[i])return 0;
        }
        report->status=VBAT_ADMIT_PROFILE;
        if(!mt6762_vbat_entry_ok(words))return 0;
    }
    report->status=VBAT_ADMIT_TIMER_STUCK;
    if(last==start)return 0;
    values[0]=profile.version;
    for(unsigned i=0;i<5;i++)values[i+1]=first[MT6762_VBAT_FIXED_COUNT+i];
    report->status=VBAT_ADMIT_OK;
    return 1;
}
#endif
