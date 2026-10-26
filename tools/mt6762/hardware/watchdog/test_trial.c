/* SPDX-License-Identifier: MIT */
#include "trial_deadline.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct clean_test {uintptr_t first,last;size_t count;};
static void cleaned(uintptr_t p,void *opaque)
{
    struct clean_test *c=opaque;
    assert(!(p&63));
    if(!c->count)c->first=p;else assert(p==c->last+64);
    c->last=p;++c->count;
}
int main(void)
{
    static const char *bad[]={"","59","1801","-60","+60","0x3c","60x",
        " 60","60 ","4294967356","18446744073709551676"};
    unsigned seconds;
    for(size_t i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
        seconds=123;assert(!mtk_trial_parse(bad[i],strlen(bad[i])+1,&seconds));
        assert(!seconds);
    }
    const char unterminated[2]={'6','0'};
    assert(!mtk_trial_parse(unterminated,sizeof(unterminated),&seconds));
    assert(mtk_trial_parse("0",2,&seconds)&&!seconds);
    assert(mtk_trial_parse("60",3,&seconds)&&seconds==60);
    assert(mtk_trial_parse("1800",5,&seconds)&&seconds==1800);
    struct mtk_trial_deadline t={.seconds=60};
    assert(!mtk_trial_expired(&t,UINT64_MAX)); /* No feed: not armed. */
    mtk_trial_fed(&t,UINT64_C(90000000000));
    mtk_trial_fed(&t,UINT64_C(120000000000)); /* Cannot extend deadline. */
    assert(t.first_ns==UINT64_C(90000000000));
    assert(!mtk_trial_expired(&t,UINT64_C(149999999999)));
    assert(mtk_trial_expired(&t,UINT64_C(150000000000)));
    assert(mtk_trial_expired(&t,0)); /* Latched even with a backwards clock. */
    t=(struct mtk_trial_deadline){.seconds=0};
    mtk_trial_fed(&t,0);assert(!mtk_trial_expired(&t,UINT64_MAX));
    t=(struct mtk_trial_deadline){.seconds=1800};
    mtk_trial_fed(&t,UINT64_MAX-UINT64_C(1800000000000));
    assert(!mtk_trial_expired(&t,UINT64_MAX-1));
    assert(mtk_trial_expired(&t,UINT64_MAX));
    t=(struct mtk_trial_deadline){.seconds=60};
    mtk_trial_fed(&t,100);assert(!mtk_trial_expired(&t,99));
    struct clean_test c={0};
    assert(!mtk_trial_clean_range(0x100000,1536*1024,cleaned,&c));
    assert(c.count==24576&&c.first==0x100000&&c.last==0x27ffc0);
    c=(struct clean_test){0};
    assert(!mtk_trial_clean_range(0x103f,2,cleaned,&c));
    assert(c.count==2&&c.first==0x1000&&c.last==0x1040);
    c=(struct clean_test){0};
    assert(mtk_trial_clean_range(UINTPTR_MAX,2,cleaned,&c)==-1&&!c.count);
    assert(!mtk_trial_clean_range(UINTPTR_MAX,1,cleaned,&c)&&c.count==1);
    assert(!mtk_trial_clean_range(0,0,NULL,NULL));
    puts("PASS: deadline admission/bounds/anchor/latch and fixed-range cache maintenance");
}
