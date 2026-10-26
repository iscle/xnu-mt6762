#include <assert.h>
#include <stdio.h>
#include "../i2c/mtk_i2c_v2.h"
#include "mt6762_charger_setup.h"
int main(void)
{
    const struct mtk_i2c_timing timing={.clock_div=0x404,.timing=0x419,
        .ltiming=0x118,.ext=0x8001,.timeout=0x190};
    const struct mt6762_charger_setup_readback actual={4,0x419,0x118,0x8000,3,0x8001,0xa,0x190};
    assert(mt6762_charger_setup_ok(2,124800000,100000,&timing,&actual));
    assert(!mt6762_charger_setup_ok(2,124800000,100000,NULL,&actual));
    assert(!mt6762_charger_setup_ok(2,124800000,100000,&timing,NULL));
    for(unsigned field=0;field<5;field++)for(unsigned bit=0;bit<16;bit++) {
        struct mtk_i2c_timing changed=timing;
        switch(field) {
        case 0:changed.clock_div^=1u<<bit;break;
        case 1:changed.timing^=1u<<bit;break;
        case 2:changed.ltiming^=1u<<bit;break;
        case 3:changed.ext^=1u<<bit;break;
        case 4:changed.timeout^=1u<<bit;break;
        }
        assert(!mt6762_charger_setup_ok(2,124800000,100000,&changed,&actual));
    }
    struct mt6762_charger_setup_readback entry=actual;
    entry.timing=0x418;entry.io=0x1a3;entry.timeout=0;
    assert(!mt6762_charger_setup_ok(2,124800000,100000,&timing,&entry));
    const unsigned order[]={3,1,0,3,1,0};
    for(unsigned index=0;index<6;index++)for(unsigned address=0;address<128;address++)
        for(unsigned reg=0;reg<256;reg++) {
            uint8_t byte=reg;
            assert(mt6762_charger_readonly_request_ok(index,address,&byte,1,1)==
                (address==0x6a && reg==order[index]));
        }
    for(unsigned index=0;index<6;index++) {
        uint8_t byte=order[index];
        for(unsigned tx=0;tx<10;tx++)for(unsigned rx=0;rx<10;rx++)
            assert(mt6762_charger_readonly_request_ok(index,0x6a,&byte,tx,rx)==(tx==1 && rx==1));
        assert(!mt6762_charger_readonly_request_ok(index,0x6a,NULL,1,1));
    }
    uint8_t id=3;
    assert(!mt6762_charger_readonly_request_ok(6,0x6a,&id,1,1));
    assert(!mt6762_charger_readonly_request_ok(UINT32_MAX,0x6a,&id,1,1));
    puts("capture31 matcher and bounded PSC address/register/shape policy PASS");
}
