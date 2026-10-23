#include "thermistor.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    int t=1234;
    /* Exact divider/table points; recovered table25C=10k and0C=27219. */
    assert(!mt6357_ntc_temperature(900,1800,10000,&t)&&t==250);
    assert(!mt6357_ntc_temperature(900,1800,27219,&t)&&t==0);
    assert(!mt6357_ntc_temperature(900,1800,195652,&t)&&t==-400);
    assert(!mt6357_ntc_temperature(900,1800,3014,&t)&&t==600);
    /* Passive ADC sample, no current correction; merely nominal estimate. */
    assert(!mt6357_ntc_temperature(614,1797,16900,&t)&&t==286);
    t=1234;
    assert(mt6357_ntc_temperature(0,1800,16900,&t)==-1&&t==1234);
    assert(mt6357_ntc_temperature(1800,1800,16900,&t)==-1&&t==1234);
    assert(mt6357_ntc_temperature(1799,1800,16900,&t)==-1&&t==1234);
    assert(mt6357_ntc_temperature(1,1800,16900,&t)==-1&&t==1234);
    puts("PASS: nominal recovered NTC table, divider, interpolation and fault rejection");
}
