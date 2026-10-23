#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../../../bsd/dev/mt6762_sspm_protocol.h"
struct fixture {
    uint32_t words[64],in,out,response,doorbell,clear;
    unsigned pin,reads,writes,polls,delays,barriers,ack_after,active;
    unsigned fail_read,fail_write,stuck_clear,stuck_input,payload_read,clear_before_read;
};
static int read32(void *p,unsigned region,uint32_t offset,uint32_t *value)
{
    struct fixture *f=p;f->reads++;
    if(f->fail_read==f->reads)return -1;
    assert(!(offset&3));
    if(region==MT6762_SSPM_DATA) {
        assert(offset<256);*value=f->words[offset/4];f->payload_read++;return 0;
    }
    assert(region==MT6762_SSPM_CTRL && offset<=4);
    if(offset==0) {*value=f->in;return 0;}
    if(f->active && ++f->polls>=f->ack_after) {
        f->out|=1u<<f->pin;
        if(!f->stuck_input)f->in&=~(1u<<f->pin);
        f->words[f->pin?3:0]=f->response;
    }
    *value=f->out;return 0;
}
static int write32(void *p,unsigned region,uint32_t offset,uint32_t value)
{
    struct fixture *f=p;f->writes++;
    if(f->fail_write==f->writes)return -1;
    if(region==MT6762_SSPM_DATA) {
        unsigned start=f->pin?12:0,count=f->pin?16:12;
        assert(offset>=start && offset<start+count && !(offset&3));
        f->words[offset/4]=value;return 0;
    }
    assert(region==MT6762_SSPM_CTRL && offset<=4);
    assert(value==(1u<<f->pin));
    if(!offset) {f->in|=value;f->doorbell=value;f->active=1;}
    else {
        f->clear=value;
        if(!f->payload_read)f->clear_before_read=1;
        if(!f->stuck_clear)f->out&=~value;
        f->active=0;
    }
    return 0;
}
static void barrier(void *p) {((struct fixture *)p)->barriers++;}
static void delay_us(void *p,unsigned delay) {assert(delay==10);((struct fixture *)p)->delays+=delay;}
static struct mt6762_sspm_transport make(struct fixture *f)
{
    struct mt6762_sspm_transport t={{f,read32,write32,barrier,delay_us},3,0};return t;
}
int main(void)
{
    const uint32_t platform[3]={0xdead,0,0},cpu[4]={0x11223344,1,2,3};
    uint32_t ack=0xfeedbeef;
    struct fixture f={.response=1,.ack_after=3,.out=0x80};
    struct mt6762_sspm_transport t=make(&f);
    assert(!mt6762_sspm_exchange(&t,0,platform,3,&ack,5));
    assert(ack==1 && f.out==0x80 && f.clear==1 && !f.clear_before_read && !f.in);
    assert(f.delays==20 && f.writes==5 && f.words[1]==0 && f.words[2]==0 && !t.fault);
    f=(struct fixture){.pin=1,.response=0x87654321,.ack_after=1};t=make(&f);
    assert(!mt6762_sspm_exchange(&t,1,cpu,4,&ack,5));
    assert(ack==0x87654321 && f.doorbell==2 && f.clear==2 && f.writes==6);
    assert(f.words[4]==1 && f.words[5]==2 && f.words[6]==3 && !f.words[0]);
    f=(struct fixture){.in=1};t=make(&f);ack=99;
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_BUSY);
    assert(t.fault && !f.writes && ack==99);
    f=(struct fixture){.out=1};t=make(&f);
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_BUSY && !f.writes);
    f=(struct fixture){.ack_after=99999,.out=0x80};t=make(&f);
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_TIMEOUT);
    assert(ack==99 && t.fault && f.delays==50 && f.writes==4 && f.out==0x80);
    unsigned reads=f.reads,writes=f.writes;
    f.out|=1; /* A late ACK cannot be consumed by a new transaction. */
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_FAULT);
    assert(f.reads==reads && f.writes==writes && f.out==0x81);
    f=(struct fixture){.ack_after=1,.response=1,.stuck_clear=1};t=make(&f);
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_IO && ack==99 && t.fault);
    f=(struct fixture){.ack_after=1,.response=1,.stuck_input=1};t=make(&f);
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_IO && ack==99 && t.fault);
    assert(f.clear==0 && f.in==1 && f.out==1);
    for(unsigned i=1;i<=6;i++) {
        f=(struct fixture){.ack_after=1,.response=1,.fail_read=i};t=make(&f);
        assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_IO && ack==99 && t.fault);
    }
    for(unsigned i=1;i<=5;i++) {
        f=(struct fixture){.ack_after=1,.response=1,.fail_write=i};t=make(&f);
        assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_IO && ack==99 && t.fault);
    }
    f=(struct fixture){0};t=make(&f);
    assert(mt6762_sspm_exchange(&t,2,platform,3,&ack,5)==MT6762_SSPM_INVALID);
    assert(mt6762_sspm_exchange(&t,0,platform,2,&ack,5)==MT6762_SSPM_INVALID);
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,0)==MT6762_SSPM_INVALID);
    t.owned_pins=0;
    assert(mt6762_sspm_exchange(&t,0,platform,3,&ack,5)==MT6762_SSPM_INVALID);
    assert(!f.reads && !f.writes && ack==99);
    puts("native SSPM ownership, slot layout, bounded ACK, W1C preservation, stale/error handling: PASS");
    return 0;
}
