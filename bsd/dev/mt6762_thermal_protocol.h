/* Independent implementation of recovered MT6765/MT6357 calibration and
 * measurement contracts. Source/stock evidence is in tools/mt6762/hardware/
 * cpu-power/THERMAL.rst. No fabricated calibration or control policy. */
#ifndef MT6762_THERMAL_PROTOCOL_H
#define MT6762_THERMAL_PROTOCOL_H
#include <stdint.h>
struct mt6762_cpu_cal { int gain, offset, half_degrees, slope_den, room[5]; };
struct mt6762_pmic_cal { int intercept[3], slope_den[3]; };
static inline unsigned mt6762_thermal_unexpired(unsigned mask,const uint64_t deadlines[8],uint64_t now)
{
    unsigned result=0;
    for(unsigned i=0;i<8;i++)if((mask&(1u<<i)) && now<deadlines[i])result|=1u<<i;
    return result;
}
static inline int mt6762_cpu_cal_decode(const uint32_t words[3],struct mt6762_cpu_cal *out)
{
    if(!words || !out)return -1;
    struct mt6762_cpu_cal c;
    unsigned a=words[1],b=words[0],d=words[2]; /* NVMEM190: temp1,temp0,temp2. */
    int gain=(int)(a>>22),offset=(a>>12)&1023,deg=(b>>1)&63;
    int slope=(a&512)?(int)(b>>26):0;
    unsigned vts[5]={(b>>17)&511,(b>>8)&511,a&511,d>>23,(d>>5)&511};
    if(!out || !(b&1) || gain<265 || gain>758 || offset<265 || offset>758 || !deg)return -1;
    c.gain=10000+(gain-512)*10000/4096;c.offset=offset-512;c.half_degrees=deg;
    c.slope_den=1534+((b&128)?-10:10)*slope;
    for(unsigned i=0;i<5;i++) {
        if(vts[i]>484)return -1;
        c.room[i]=(((int)vts[i]+3350-c.offset)*10000/4096)*10000/c.gain;
    }
    *out=c;return 0;
}
static inline int mt6762_cpu_temperature(const struct mt6762_cpu_cal *c,unsigned sensor,unsigned raw,int *mc)
{
    int64_t x,t;
    if(!c || !mc || sensor>=5 || raw==0 || raw>=4095 || c->gain<=0 || c->slope_den<=0)return -1;
    x=((int64_t)raw-c->offset)*10000;
    /* AArch64 arithmetic shift is floor division, including negative inputs. */
    x=x>=0?x/4096:-((-x+4095)/4096);
    x=(x*10000/c->gain-c->room[sensor])*15/18;
    t=((c->half_degrees*10)/2-x*1000/c->slope_den)*100;
    if(t < -50000 || t > 150000)return -1;
    *mc=(int)t;return 0;
}
/* Words are PMIC11ae,11b0,11b2,11b4,11b6,11b8. */
static inline int mt6762_pmic_cal_decode(const uint16_t words[6],struct mt6762_pmic_cal *out)
{
    if(!words || !out)return -1;
    struct mt6762_pmic_cal c;
    unsigned deg=words[0]&63,slope=(words[3]&16)?words[2]&63:0;
    unsigned vts[3]={words[1]&8191,words[4]&8191,words[5]&8191};
    int sign=(words[2]&256)?-1:1;
    if(!out || !(words[0]&256) || deg<38 || deg>60)return -1;
    for(unsigned i=0;i<3;i++) {
        int factor=i?1863:1681;
        if(!vts[i] || vts[i]>=4095)return -1;
        c.slope_den[i]=-(factor+sign*(int)slope);
        c.intercept[i]=(int)((int64_t)(vts[i]*1800/4096)*1000000/
            (factor+sign*(int)slope*10))+deg*500;
    }
    *out=c;return 0;
}
static inline int mt6762_pmic_temperature(const struct mt6762_pmic_cal *c,unsigned sensor,unsigned raw,int *mc)
{
    int64_t value;
    if(!c || !mc || sensor>=3 || !raw || raw>=4095 || c->slope_den[sensor]>=0)return -1;
    unsigned mv=raw*1800/4096;
    value=c->intercept[sensor]+(int64_t)mv*1000000/c->slope_den[sensor];
    if(value < -50000 || value > 150000)return -1;
    *mc=(int)value;return 0;
}
struct mt6762_thermal_adc_io {
    void *context;
    int (*read)(void *,uint16_t,uint16_t *);
    int (*write)(void *,uint16_t,uint16_t);
    void (*delay_us)(void *,unsigned);
};
/* Only measurement requests are written. Caller owns ADC/MUX serialization.
 * A READY low->high transition is mandatory: cached READY is not freshness. */
static inline int mt6762_thermal_adc(const struct mt6762_thermal_adc_io *io,unsigned sensor,uint16_t *out)
{
    static const uint16_t output[3]={0x1090,0x10d8,0x10da};
    uint16_t word,mux,raw;
    int e;
    if(!io || !io->read || !io->write || !io->delay_us || !out || sensor>=3)return -1;
    if((e=io->read(io->context,0x1216,&mux)))return e;
    if(sensor==0 && (mux&16))return -2; /* DCXO owns shared CH4 mux. */
    if((e=io->write(io->context,sensor?0x1114:0x110e,(uint16_t)(1u<<(sensor?4+sensor:4)))))return e;
    if((e=io->read(io->context,output[sensor],&word)))return e;
    if(word&0x8000)return -5; /* No observed conversion transition. */
    io->delay_us(io->context,80); /* Default DT8 averages,10us each. */
    for(unsigned n=0;n<160;n++) {
        if((e=io->read(io->context,output[sensor],&word)))return e;
        if(word&0x8000) {
            raw=word&4095;
            if(!raw || raw==4095)return -4;
            if((e=io->read(io->context,0x1216,&word)))return e;
            if(sensor==0 && ((word^mux)&16))return -2;
            *out=raw;return 0;
        }
        io->delay_us(io->context,200);
    }
    return -3;
}
#endif
