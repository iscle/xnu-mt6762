/* SPDX-License-Identifier: MIT
 * MT6357 inherited gauge/ADC observation, not measurement or admission.
 * Ordinary 16-bit reads only; no latch/request/reset/SET/CLR writes. Output
 * words are sequential observations, not a coherent measurement snapshot.
 * ADC ready bits may belong to old conversions and confer no freshness.
 * Sources and remaining ownership/calibration gaps: PMIC-ENTRY.rst.
 */
#ifndef MT6762_PMIC_ENTRY_H
#define MT6762_PMIC_ENTRY_H
#include <stdint.h>

#define MT6762_PMIC_ENTRY_COUNT 13u
static const uint16_t mt6762_pmic_entry_regs[MT6762_PMIC_ENTRY_COUNT]={
    0x0008, /* HWCID: stop on an unexpected family before further reads. */
    0x0c0c, /* BM_TOP_CKPDN_CON0: gauge digital/analog clock gates. */
    0x0d08, /* FGADC_CON0: FG_ON and inherited configuration. */
    0x0d0a, /* FGADC_CON1: existing command/latch state; never clear it. */
    0x0c8e, /* FGADC_ANA_ELR0: hardware efuse gain shadow. */
    0x0c90, /* FGADC_ANA_ELR1: hardware efuse offset shadow. */
    0x0d94, /* FGADC_OFFSET_CON1: manual offset adjustment. */
    0x0d96, /* FGADC_GAIN_CON0: hardware gain configuration. */
    0x0e08, /* BATON_ANA_CON0: detector enable and absence state. */
    0x108a, /* AUXADC_ADC1: previous battery voltage result/ready. */
    0x108e, /* AUXADC_ADC3: previous thermistor result/ready. */
    0x109e, /* AUXADC_ADC11: previous BIF result/ready. */
    0x1236  /* AUXADC_CHR_TOP_CON2: inherited BATON_TDET_EN. */
};
typedef int (*mt6762_pmic_entry_read)(void *,uint16_t,uint16_t *);
struct mt6762_pmic_entry_observation {
    uint16_t value[MT6762_PMIC_ENTRY_COUNT];
};
struct mt6762_pmic_entry_failure {
    unsigned index;
    uint16_t address,value;
    int error;
};
/* Return -1 for invalid arguments, -2 for transport failure, -3 for a wrong
 * PMIC family. On failure leave *out untouched; never retry a failed read.
 * Busy/disabled gauge fields and zero/stale ADC words are valid raw evidence,
 * not grounds to clear a latch, start a conversion, or grant ownership. */
static inline int mt6762_pmic_entry_observe(mt6762_pmic_entry_read read,
    void *context,struct mt6762_pmic_entry_observation *out,
    struct mt6762_pmic_entry_failure *failure)
{
    struct mt6762_pmic_entry_observation next;
    if(!read || !out) {
        if(failure)*failure=(struct mt6762_pmic_entry_failure){0,0,0,-1};
        return -1;
    }
    for(unsigned i=0;i<MT6762_PMIC_ENTRY_COUNT;i++) {
        uint16_t value=0;
        int error=read(context,mt6762_pmic_entry_regs[i],&value);
        if(error || (!i && (value>>8)!=0x57)) {
            if(failure)*failure=(struct mt6762_pmic_entry_failure){
                i,mt6762_pmic_entry_regs[i],error?0:value,error};
            return error?-2:-3;
        }
        next.value[i]=value;
    }
    *out=next;
    return 0;
}

/* Independent version1 ADC configuration record. Keep the preceding13-word
 * record and API unchanged for existing physical capture decoders. HWCID is
 * reread first; the remaining18 ordinary words fill the missing SWCID and
 * native BIF configuration inventory. This does not request conversions or
 * infer calibration from equality, zero/nonzero values or chip revision. */
#define MT6762_PMIC_ADC_ENTRY_COUNT 19u
static const uint16_t mt6762_pmic_adc_entry_regs[MT6762_PMIC_ADC_ENTRY_COUNT]={
    0x0008, /* HWCID: independent identity guard for this pass. */
    0x000a, /* SWCID. */
    0x10de, /* AUXADC_DIG_1_ELR0: inherited software gain trim. */
    0x10e0, /* AUXADC_DIG_1_ELR1: inherited software offset trim. */
    0x1120, /* AUXADC_CON0; not SET/CLR aliases. */
    0x1126, /* AUXADC_CON1. */
    0x1128, /* AUXADC_CON2. */
    0x112e, /* AUXADC_CON5. */
    0x1132, /* AUXADC_CON7. */
    0x1136, /* AUXADC_CON9. */
    0x113a, /* AUXADC_CON11. */
    0x113c, /* AUXADC_CON12. */
    0x1008, /* AUXADC_ANA_CON0. */
    0x11a2, /* AUXADC_DIG_3_ELR0. */
    0x11a4, /* AUXADC_DIG_3_ELR1. */
    0x11a6, /* AUXADC_DIG_3_ELR2. */
    0x11a8, /* AUXADC_DIG_3_ELR3. */
    0x11aa, /* AUXADC_DIG_3_ELR4. */
    0x11ac  /* AUXADC_DIG_3_ELR5. */
};
struct mt6762_pmic_adc_entry_observation {
    uint16_t value[MT6762_PMIC_ADC_ENTRY_COUNT];
};
static inline int mt6762_pmic_adc_entry_observe(mt6762_pmic_entry_read read,
    void *context,struct mt6762_pmic_adc_entry_observation *out,
    struct mt6762_pmic_entry_failure *failure)
{
    struct mt6762_pmic_adc_entry_observation next;
    if(!read || !out) {
        if(failure)*failure=(struct mt6762_pmic_entry_failure){0,0,0,-1};
        return -1;
    }
    for(unsigned i=0;i<MT6762_PMIC_ADC_ENTRY_COUNT;i++) {
        uint16_t value=0;
        int error=read(context,mt6762_pmic_adc_entry_regs[i],&value);
        if(error || (!i && (value>>8)!=0x57)) {
            if(failure)*failure=(struct mt6762_pmic_entry_failure){
                i,mt6762_pmic_adc_entry_regs[i],error?0:value,error};
            return error?-2:-3;
        }
        next.value[i]=value;
    }
    *out=next;
    return 0;
}
#endif
