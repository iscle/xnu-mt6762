#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../../../bsd/dev/mt6762_thermal_protocol.h"
#include "thermal_slopes.h"
struct fixture {unsigned writes,reads,delays,sensor,fault;uint16_t raw;};
static int read16(void *p,uint16_t reg,uint16_t *out)
{
    struct fixture *f=p;f->reads++;
    if(f->fault==6)return -6;
    if(reg==0x1216) {*out=f->fault==1?16:0;return 0;}
    assert(reg==(f->sensor==0?0x1090:f->sensor==1?0x10d8:0x10da));
    *out=f->raw;
    if(f->fault==2 || (f->delays && f->fault!=3))*out|=0x8000;
    return 0;
}
static int write16(void *p,uint16_t reg,uint16_t value)
{
    struct fixture *f=p;f->writes++;
    assert(reg==(f->sensor?0x1114:0x110e));
    assert(value==(1u<<(f->sensor?4+f->sensor:4)));
    return f->fault==5?-5:0;
}
static void wait_us(void *p,unsigned us) {struct fixture *f=p;assert(us==80||us==200);f->delays++;}
int main(void)
{
    /* Independent expected values from bounded original boot calibration logs. */
    const uint32_t cpu_words[3]={0x0299546b,0x9d9d514c,0xa5d36940};
    const uint16_t pmic_words[6]={0x137,1588,0,0,1526,1534};
    struct mt6762_cpu_cal cpu,unchanged_cpu;
    struct mt6762_pmic_cal pmic,unchanged_pmic;
    int mc=123,previous=200000;
    uint32_t bad_cpu[3];uint16_t bad_pmic[6];
    assert(!mt6762_cpu_cal_decode(cpu_words,&cpu));
    assert(cpu.gain==10288 && cpu.offset==-43 && cpu.half_degrees==53);
    const int rooms[5]={8839,8857,8839,8836,8834};
    for(unsigned i=0;i<5;i++)assert(cpu.room[i]==rooms[i]);
    assert(!mt6762_cpu_temperature(&cpu,0,3682,&mc) && mc==26500);
    for(unsigned raw=1;raw<4095;raw++)if(!mt6762_cpu_temperature(&cpu,0,raw,&mc)){assert(mc<=previous);previous=mc;}
    assert(!mt6762_pmic_cal_decode(pmic_words,&pmic));
    assert(pmic.intercept[0]==442134 && pmic.slope_den[0]==-1681);
    assert(pmic.intercept[1]==387134 && pmic.intercept[2]==389282);
    for(unsigned i=0;i<3;i++)assert(!mt6762_pmic_temperature(&pmic,i,pmic_words[i==0?1:i+3],&mc) && mc==27500);
    unchanged_cpu=cpu;unchanged_pmic=pmic;
    memcpy(bad_cpu,cpu_words,sizeof(bad_cpu));bad_cpu[0]&=~1u;
    assert(mt6762_cpu_cal_decode(bad_cpu,&cpu) && !memcmp(&cpu,&unchanged_cpu,sizeof(cpu)));
    memcpy(bad_cpu,cpu_words,sizeof(bad_cpu));bad_cpu[1]&=0x003fffff;
    assert(mt6762_cpu_cal_decode(bad_cpu,&cpu));
    memcpy(bad_pmic,pmic_words,sizeof(bad_pmic));bad_pmic[0]&=~256u;
    assert(mt6762_pmic_cal_decode(bad_pmic,&pmic) && !memcmp(&pmic,&unchanged_pmic,sizeof(pmic)));
    memcpy(bad_pmic,pmic_words,sizeof(bad_pmic));bad_pmic[0]=0x101;
    assert(mt6762_pmic_cal_decode(bad_pmic,&pmic));
    mc=123;assert(mt6762_cpu_temperature(&cpu,0,0,&mc) && mc==123);
    assert(mt6762_pmic_temperature(&pmic,0,4095,&mc) && mc==123);
    assert(mt6762_cpu_cal_decode(NULL,&cpu) && mt6762_pmic_cal_decode(NULL,&pmic));
    /* Independently produced by executing original stock AArch64 function. */
    for(unsigned i=0;i<sizeof(thermal_slopes)/sizeof(thermal_slopes[0]);i++) {
        struct mt6762_pmic_cal slopes;
        memcpy(bad_pmic,pmic_words,sizeof(bad_pmic));
        bad_pmic[2]=(uint16_t)(thermal_slopes[i][0]|(thermal_slopes[i][1]<<8));
        bad_pmic[3]=16; /* ID1 preserves slope. */
        assert(!mt6762_pmic_cal_decode(bad_pmic,&slopes));
        for(unsigned j=0;j<3;j++) {
            assert(slopes.slope_den[j]==thermal_slopes[i][j+2]);
            assert(slopes.intercept[j]==thermal_slopes[i][j+5]);
        }
        bad_pmic[3]=0; /* ID0 ignores even nonzero efuse slope. */
        assert(!mt6762_pmic_cal_decode(bad_pmic,&slopes));
        assert(!memcmp(&slopes,&unchanged_pmic,sizeof(slopes)));
    }
    const uint64_t deadlines[8]={10,11,12,13,14,15,16,17};
    assert(mt6762_thermal_unexpired(255,deadlines,9)==255);
    assert(mt6762_thermal_unexpired(255,deadlines,10)==254);
    assert(mt6762_thermal_unexpired(255,deadlines,17)==0);
    assert(mt6762_thermal_unexpired(1,deadlines,9)==1);
    for(unsigned sensor=0;sensor<3;sensor++)for(unsigned fault=0;fault<=6;fault++) {
        struct fixture f={.sensor=sensor,.fault=fault,.raw=fault==4?4095:1588};
        struct mt6762_thermal_adc_io io={&f,read16,write16,wait_us};uint16_t raw=1234;
        int e=mt6762_thermal_adc(&io,sensor,&raw);
        if(!fault || (fault==1 && sensor))assert(!e && raw==1588 && f.writes==1);
        else {assert(e && raw==1234);if(fault==1 || fault==6)assert(!f.writes);}
        assert(f.delays<=161);
    }
    puts("native thermal calibration/freshness tests: PASS");
}
