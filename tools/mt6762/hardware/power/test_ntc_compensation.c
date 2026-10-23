#include "thermistor.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "ntc_vectors.h"
int main(void)
{
    for(unsigned i=0;i<sizeof(ntc_vectors)/sizeof(ntc_vectors[0]);i++) {
        const int *v=ntc_vectors[i];int value=INT_MIN;
        assert(!mt6357_ntc_compensated_temperature(v[0],v[1],16900,
            v[2]*100,v[3],v[4],v[5],&value));
        assert(value==v[6]);
    }
    int value=1234;
    assert(mt6357_ntc_compensated_temperature(0,1800,16900,0,100,0,0,&value));
    assert(mt6357_ntc_compensated_temperature(1800,1800,16900,0,100,0,0,&value));
    assert(mt6357_ntc_compensated_temperature(1,1800,16900,10000000,1000,0,0,&value));
    assert(mt6357_ntc_compensated_temperature(614,1797,16900,0,100,0,2,&value));
    assert(mt6357_ntc_compensated_temperature(614,1797,16900,INT_MIN,UINT32_MAX,UINT32_MAX,0,&value));
    assert(value==1234);
    puts("PASS: stock NTC compensation ARM64 vectors; invalid rails/configurations preserve output");
}
