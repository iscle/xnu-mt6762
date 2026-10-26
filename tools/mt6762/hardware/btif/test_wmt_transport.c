#include "btif_wmt.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
/* An eight-byte RX FIFO and a peer that stops when handshake deasserts.
 * This tests the software contract, not physical CONSYS flow control. */
static const uint8_t query[]={0x80,0x40,5,0,1,4,1,0,4,0,0};
static const uint8_t event[]={0x80,0x40,10,0,2,4,6,0,0,4,0x11,0,0,0,0,0};
struct peripheral {
    uint32_t regs[32];
    uint8_t fifo[8],reply[sizeof(event)],tx[sizeof(query)];
    size_t count,head,produced,tx_length;
    unsigned accesses,writes8,backpressure,tx_empty,ready;
};
static int accessible(void *v) {return ((struct peripheral *)v)->ready;}
static uint32_t read32(void *v,unsigned r)
{
    struct peripheral *p=v;assert(p->ready);p->accesses++;assert(r && r<128);
    if(r==20)return (p->tx_empty?0x40u:0)|(p->count?1u:0);
    if(r==8)return p->count?0x44:1;
    return p->regs[r/4];
}
static void write32(void *v,unsigned r,uint32_t value)
{
    struct peripheral *p=v;assert(p->ready);p->accesses++;
    assert(r==4 || r==12 || r==0x4c || r==0x60 || r==0x6c);
    p->regs[r/4]=value;
}
static uint8_t read8(void *v,unsigned r)
{
    struct peripheral *p=v;assert(p->ready && !r && p->count);
    p->accesses++;uint8_t value=p->fifo[p->head];
    p->head=(p->head+1)%8;p->count--;return value;
}
static void write8(void *v,unsigned r,uint8_t value)
{
    struct peripheral *p=v;assert(p->ready && !r && p->tx_length<sizeof(p->tx));
    p->accesses++;p->writes8++;p->tx[p->tx_length++]=value;p->tx_empty=0;
}
static void produce(struct peripheral *p)
{
    if(p->tx_length!=sizeof(query))return;
    assert(!memcmp(query,p->tx,sizeof(query)) && (p->regs[0x6c/4]&1));
    while(p->produced<sizeof(event)) {
        if(p->count==8){p->backpressure++;break;}
        p->fifo[(p->head+p->count)%8]=p->reply[p->produced++];p->count++;
    }
}
static void start(struct btif_wmt_query *s,struct peripheral *p)
{
    memset(s,0,sizeof(*s));memset(p,0,sizeof(*p));
    p->tx_empty=1;p->ready=1;memcpy(p->reply,event,sizeof(event));
    const struct btif_pio_io io={p,accessible,read32,write32,read8,write8};
    const struct btif_pio_grant grant={1,1,1,1};
    assert(btif_wmt_start(s,&io,&grant,0,100000)==0);
}
static void successful(void)
{
    struct btif_wmt_query s;struct peripheral p;start(&s,&p);
    assert(btif_wmt_step(&s,1)==0 && p.tx_length==sizeof(query));
    p.tx_empty=1;produce(&p);assert(p.count==8 && p.backpressure==1);
    assert(btif_wmt_step(&s,5000)==0 && s.phase==BTIF_WMT_QUERY && !p.count);
    produce(&p);assert(p.count==8);
    assert(btif_wmt_step(&s,10000)==0 && s.phase==BTIF_WMT_DEFAULT_OPTIONS);
    assert(s.protocol.events==1 && s.transport.tx_written==sizeof(query));
    assert(p.produced==sizeof(event) && !p.count && !s.protocol.pda_ready);
    unsigned a=p.accesses;assert(btif_wmt_step(&s,10001)<0 && a==p.accesses);
}
static void failures(void)
{
    for(unsigned variant=0;variant<5;variant++) {
        struct btif_wmt_query s;struct peripheral p;start(&s,&p);
        if(variant==0){p.fifo[0]=0x80;p.count=1;}
        int r=btif_wmt_step(&s,1);
        if(variant==0){assert(r<0 && !p.tx_length);continue;}
        assert(r==0);p.tx_empty=variant!=1;
        if(variant==2)p.reply[8]=1; /* Firmware status failure. */
        produce(&p);
        if(variant==3)p.ready=0;
        r=btif_wmt_step(&s,variant==4?100000:5);
        if(variant==3 || variant==4){assert(r<0);continue;}
        assert(r==0);produce(&p);r=btif_wmt_step(&s,10);
        if(variant==2)assert(r<0 && s.protocol_error==CW_STATUS);
        if(variant==1){
            assert(r==0 && s.phase==BTIF_WMT_QUERY && !s.transport.tx_complete);
            assert(btif_wmt_step(&s,100000)<0 && s.phase==BTIF_WMT_FAILED);
        }
        assert(s.phase!=BTIF_WMT_DEFAULT_OPTIONS);
    }
}
static void small_capacity(void)
{
    struct btif_wmt_query s;struct peripheral p;start(&s,&p);
    assert(btif_wmt_step(&s,1)==0);p.tx_empty=1;
    /* Exercise the same FIFO with a caller buffer smaller than its capacity. */
    uint8_t bytes[2],all[sizeof(event)];size_t n,total=0;
    for(unsigned i=0;total<sizeof(event);i++){
        produce(&p);assert(p.count<=8);
        assert(btif_pio_step(&s.transport,bytes,sizeof(bytes),&n,2+i*1000)==0);
        assert(n && n<=2);memcpy(all+total,bytes,n);total+=n;assert(i<20);
    }
    assert(!memcmp(all,event,sizeof(event)) && p.backpressure>=4);
}
int main(void)
{
    successful();failures();small_capacity();
    puts("BTIF/WMT: eight-byte FIFO, backpressure, exact default query and failed exchanges passed");
    return 0;
}
