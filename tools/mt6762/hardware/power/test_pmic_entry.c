#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "mt6762_pmic_entry.h"

/* Independent literal allowlist: no request, SET/CLR alias or current/CAR
 * latch data may silently enter this passive configuration observer. */
static const uint16_t expected[]={0x8,0xc0c,0xd08,0xd0a,0xc8e,0xc90,
    0xd94,0xd96,0xe08,0x108a,0x108e,0x109e,0x1236};
static uint16_t words[13];
static unsigned reads;
static int fail_at=-1;
static int read_word(void *context,uint16_t address,uint16_t *value)
{
    assert(context==words && reads<13 && address==expected[reads]);
    unsigned index=reads++;
    *value=words[index]; /* A failed transport may have modified its output. */
    return (int)index==fail_at?-71:0;
}
static void reset(void)
{
    reads=0;fail_at=-1;
    for(unsigned i=0;i<13;i++)words[i]=(uint16_t)(0x8000+i);
    words[0]=0x5730;
}
static const uint16_t adc_expected[]={0x8,0xa,0x10de,0x10e0,0x1120,0x1126,
    0x1128,0x112e,0x1132,0x1136,0x113a,0x113c,0x1008,
    0x11a2,0x11a4,0x11a6,0x11a8,0x11aa,0x11ac};
static uint16_t adc_words[19];
static int adc_read_word(void *context,uint16_t address,uint16_t *value)
{
    assert(context==adc_words && reads<19 && address==adc_expected[reads]);
    unsigned index=reads++;
    *value=adc_words[index];
    return (int)index==fail_at?-71:0;
}
static void adc_reset(void)
{
    reads=0;fail_at=-1;
    for(unsigned i=0;i<19;i++)adc_words[i]=(uint16_t)(0x3100+i);
    adc_words[0]=0x5730;
}
static void adc_cases(void)
{
    struct mt6762_pmic_adc_entry_observation out,before;
    struct mt6762_pmic_entry_failure failure;
    assert(MT6762_PMIC_ADC_ENTRY_COUNT==19);
    assert(!memcmp(mt6762_pmic_adc_entry_regs,adc_expected,sizeof(adc_expected)));
    adc_reset();
    assert(!mt6762_pmic_adc_entry_observe(adc_read_word,adc_words,&out,&failure));
    assert(reads==19 && !memcmp(out.value,adc_words,sizeof(adc_words)));
    /* Configuration values are raw evidence: zero/all-ones and a revision
     * different from previous samples must not invent a calibration grant. */
    for(unsigned mode=0;mode<2;mode++) {
        adc_reset();
        for(unsigned i=1;i<19;i++)adc_words[i]=mode?0xffff:0;
        assert(!mt6762_pmic_adc_entry_observe(adc_read_word,adc_words,&out,NULL));
        assert(reads==19 && !memcmp(out.value,adc_words,sizeof(adc_words)));
    }
    memset(&before,0xa5,sizeof(before));
    for(unsigned i=0;i<19;i++) {
        adc_reset();fail_at=(int)i;out=before;
        assert(mt6762_pmic_adc_entry_observe(adc_read_word,adc_words,&out,&failure)==-2);
        assert(reads==i+1 && failure.index==i && failure.address==adc_expected[i]);
        assert(failure.error==-71 && failure.value==0);
        assert(!memcmp(&out,&before,sizeof(out)));
    }
    for(unsigned id=0;id<=0xffff;id++) {
        if((id>>8)==0x57)continue;
        adc_reset();adc_words[0]=(uint16_t)id;out=before;
        assert(mt6762_pmic_adc_entry_observe(adc_read_word,adc_words,&out,&failure)==-3);
        assert(reads==1 && failure.index==0 && failure.address==8);
        assert(failure.value==id && failure.error==0);
        assert(!memcmp(&out,&before,sizeof(out)));
    }
    adc_reset();out=before;
    assert(mt6762_pmic_adc_entry_observe(NULL,adc_words,&out,&failure)==-1);
    assert(mt6762_pmic_adc_entry_observe(adc_read_word,adc_words,NULL,NULL)==-1);
    assert(!reads && !memcmp(&out,&before,sizeof(out)));
}
int main(void)
{
    struct mt6762_pmic_entry_observation out,before;
    struct mt6762_pmic_entry_failure failure;
    assert(MT6762_PMIC_ENTRY_COUNT==13);
    reset();
    assert(!mt6762_pmic_entry_observe(read_word,words,&out,&failure));
    assert(reads==13 && !memcmp(out.value,words,sizeof(words)));
    /* Gates shut, gauge off, another owner's latch set, detector disabled,
     * ADC zero/not-ready and ADC maximum/ready remain raw observations. */
    reset();words[1]=0x18;words[2]=0;words[3]=0x8009;words[8]=0;
    words[9]=0;words[10]=0xffff;words[11]=0x8000;words[12]=2;
    assert(!mt6762_pmic_entry_observe(read_word,words,&out,NULL));
    assert(reads==13 && !memcmp(out.value,words,sizeof(words)));
    memset(&before,0xa5,sizeof(before));
    for(unsigned i=0;i<13;i++) {
        reset();fail_at=(int)i;out=before;
        assert(mt6762_pmic_entry_observe(read_word,words,&out,&failure)==-2);
        assert(reads==i+1 && failure.index==i && failure.address==expected[i]);
        assert(failure.error==-71 && failure.value==0);
        assert(!memcmp(&out,&before,sizeof(out)));
    }
    reset();words[0]=0xffff;out=before;
    assert(mt6762_pmic_entry_observe(read_word,words,&out,&failure)==-3);
    assert(reads==1 && failure.index==0 && failure.address==8);
    assert(failure.value==0xffff && failure.error==0);
    assert(!memcmp(&out,&before,sizeof(out)));
    reset();out=before;
    assert(mt6762_pmic_entry_observe(NULL,words,&out,&failure)==-1);
    assert(mt6762_pmic_entry_observe(read_word,words,NULL,NULL)==-1);
    assert(!reads && !memcmp(&out,&before,sizeof(out)));
    adc_cases();
    puts("passive PMIC entry: fixed reads, raw busy/stale state, atomic failure, no retry PASS");
    puts("passive ADC entry: independent fixed19-word record, raw config, wrong-ID/partial stop PASS");
}
