#include "mtk_i2c_v2.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct model {
    uint16_t reg[128]; uint32_t dma[32]; uint8_t buffer[64];
    unsigned writes, delays, barriers, running, error, stall, dma_stall;
};
static uint16_t rd(void *v,unsigned o) {
    struct model *s=v;
    if(o==12 && s->running && !s->stall) {
        s->reg[36/2]=0;
        if (!s->dma_stall) s->dma[8/4]=0;
        return s->error ? (uint16_t)(s->error|1) : 1;
    }
    if(o==0) return 0x5a;
    return s->reg[o/2];
}
static void wr(void *v,unsigned o,uint16_t x) {
    struct model *s=v; s->writes++;
    if(o==12) s->reg[o/2]&=(uint16_t)~x; else s->reg[o/2]=x;
    if(o==36 && x==1) {
        s->running=1;
        for(unsigned i=0;i<s->dma[40/4];i++) s->buffer[i]=(uint8_t)(i+1);
    }
}
static uint32_t dr(void *v,unsigned o) {return ((struct model *)v)->dma[o/4];}
static void dw(void *v,unsigned o,uint32_t x) {
    struct model *s=v; s->writes++;s->dma[o/4]=x;
}
static void barrier(void *v) {((struct model *)v)->barriers++;}
static void delay(void *v,unsigned us) {((struct model *)v)->delays+=us;}
static struct mtk_i2c_v2 init(struct model *s) {
    memset(s,0,sizeof(*s));
    return (struct mtk_i2c_v2){.context=s,.read16=rd,.write16=wr,
        .dma_read32=dr,.dma_write32=dw,.barrier=barrier,.delay_us=delay,
        .dma_buffer=s->buffer,.dma_address=0x140010000ULL,.dma_capacity=64,
        .timeout_us=20,.bus_hz=400000,.initialized=1};
}
int main(void) {
    struct model s; struct mtk_i2c_v2 b=init(&s);
    uint8_t reg=3,out[32]; memset(out,0xcc,sizeof out);
    struct mtk_i2c_msg pair[]={{0x6a,0,1,&reg},{0x6a,1,1,out}};
    assert(mtk_i2c_v2_transfer(&b,pair,2)==2);
    assert(out[0]==0x5a && s.reg[4/2]==0xd4 && s.reg[68/2]==1);
    assert(s.reg[16/2]==0x3a && s.reg[24/2]==2 && s.dma[8/4]==0);
    b=init(&s);
    struct mtk_i2c_msg touch={0x3b,1,32,out};
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==1);
    assert(s.reg[4/2]==0x77 && s.reg[16/2]==0x32c);
    assert(s.dma[32/4]==0x40010000 && s.dma[88/4]==1);
    assert(s.dma[40/4]==32 && s.dma[36/4]==0 && out[31]==32);
    assert(s.barriers==3);
    b=init(&s); pair[1].length=32;
    assert(mtk_i2c_v2_transfer(&b,pair,2)==2);
    assert(s.dma[36/4]==1 && s.dma[40/4]==32 && s.reg[16/2]==0x33e);
    b=init(&s); b.initialized=0;
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_NOT_READY && !s.writes);
    b=init(&s); s.reg[36/2]=1;
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_BUSY && !s.writes);
    b=init(&s); s.dma[8/4]=1;
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_BUSY && !s.writes);
    b=init(&s); pair[1].address=0x3b;
    assert(mtk_i2c_v2_transfer(&b,pair,2)==MTK_I2C_INVALID && !s.writes);
    b=init(&s); b.dma_address=(1ULL<<33)-16;
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_INVALID && !s.writes);
    b=init(&s); b.bus_hz=1000000;
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_INVALID && !s.writes);
    for(unsigned bit=1;bit<9;bit++) {
        if(bit==4)continue; /* repeated START notification, not failure */
        b=init(&s); s.error=1u<<bit; out[0]=0xcc;
        assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_IO);
        assert(out[0]==0xcc && b.faulted);
        unsigned previous=s.writes;
        assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_NOT_READY);
        assert(previous==s.writes);
    }
    b=init(&s); s.stall=1; out[0]=0xcc;
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_TIMEOUT);
    assert(s.delays==20 && b.faulted && out[0]==0xcc);
    b=init(&s); s.dma_stall=1;
    assert(mtk_i2c_v2_transfer(&b,&touch,1)==MTK_I2C_TIMEOUT);
    assert(s.delays==20 && b.faulted);
    puts("MTK I2C v2: FIFO, repeated START, DMA33, errors and timeout tests passed");
}
