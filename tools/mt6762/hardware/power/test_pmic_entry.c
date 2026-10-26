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
    puts("passive PMIC entry: fixed reads, raw busy/stale state, atomic failure, no retry PASS");
}
