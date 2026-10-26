#include "btif_pio.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

struct peripheral {
    uint32_t regs[32];
    uint8_t rx[4096],tx[4096];
    size_t rx_read,rx_length,tx_length,tx_fifo;
    unsigned accesses,writes,reads8,writes8,ready_calls,accessible,stuck;
};
static int ready(void *v)
{ struct peripheral *p=v; p->ready_calls++; return p->accessible; }
static uint32_t read32(void *v,unsigned r)
{
    struct peripheral *p=v; assert(p->accessible);p->accesses++;
    assert(r && !(r&3) && r<128); /* RBR/THR must never be32-bit. */
    if(r==8) return p->rx_read<p->rx_length?0x44:1;
    if(r==20) return (p->rx_read<p->rx_length?1u:0)|
        (!p->tx_fifo?0x40u:0)|(p->tx_fifo<=8?0x20u:0);
    return p->regs[r/4];
}
static void write32(void *v,unsigned r,uint32_t value)
{
    struct peripheral *p=v;assert(p->accessible);p->accesses++;p->writes++;
    assert(r==4 || r==12 || r==0x4c || r==0x60 || r==0x6c);
    /* FIFO clear, wake, DMA enable, sleep and clock writes are excluded. */
    if(r==0x4c) assert(!(value&3));
    if(r==4) assert(!(value&2));
    if(r==0x60) assert(!(value&0x80));
    if(r!=p->stuck) p->regs[r/4]=value;
}
static uint8_t read8(void *v,unsigned r)
{
    struct peripheral *p=v;assert(p->accessible && r==0);
    p->accesses++;p->reads8++;assert(p->rx_read<p->rx_length);
    return p->rx[p->rx_read++];
}
static void write8(void *v,unsigned r,uint8_t value)
{
    struct peripheral *p=v;assert(p->accessible && r==0);
    p->accesses++;p->writes8++;
    assert(p->tx_fifo<16 && p->tx_length<sizeof(p->tx));
    p->tx[p->tx_length++]=value;p->tx_fifo++;
}
static struct btif_pio_io io(struct peripheral *p)
{ return (struct btif_pio_io){p,ready,read32,write32,read8,write8}; }
static const struct btif_pio_grant grant={1,1,1,1};
static void start(struct btif_pio *s,struct peripheral *p)
{
    memset(s,0,sizeof(*s));memset(p,0,sizeof(*p));p->accessible=1;
    struct btif_pio_io ops=io(p);assert(btif_pio_init(s,&ops,&grant)==0);
    assert(s->initialized && p->regs[1]==1 && p->regs[0x4c/4]==4);
    assert(p->regs[0x60/4]==0x18 && p->regs[0x6c/4]==1);
}
static void admission(void)
{
    for(unsigned i=0;i<4;i++) {
        struct btif_pio s={0};struct peripheral p={.accessible=1};
        struct btif_pio_io ops=io(&p);struct btif_pio_grant g=grant;
        if(i==0)g.enabled=0;
        if(i==1)g.exclusive=0;
        if(i==2)g.irq_masked=0;
        if(i==3)g.apdma_idle=0;
        assert(btif_pio_init(&s,&ops,&g)<0 && !p.accesses && !p.ready_calls);
    }
    for(unsigned i=0;i<5;i++) {
        struct btif_pio s={0};struct peripheral p={.accessible=1};
        struct btif_pio_io ops=io(&p);
        if(i==0)p.accessible=0;
        if(i==1)p.regs[0x4c/4]=3;
        if(i==2)p.rx_length=1;
        if(i==3)p.tx_fifo=1;
        if(i==4)p.regs[1]=2;
        assert(btif_pio_init(&s,&ops,&grant)<0 && !p.writes && !p.reads8);
        if(i==0)assert(!p.accesses);
    }
    for(unsigned i=0;i<3;i++) {
        struct btif_pio s={0};struct peripheral p={.accessible=1};
        struct btif_pio_io ops=io(&p);
        p.stuck=i==0?0x4c:i==1?0x60:0x6c;
        assert(btif_pio_init(&s,&ops,&grant)==BTIF_CONFIG && !s.initialized);
        unsigned a=p.accesses;
        assert(btif_pio_init(&s,&ops,&grant)==BTIF_STATE && p.accesses==a);
    }
}
static void fifo_progress(void)
{
    struct btif_pio s;struct peripheral p;uint8_t tx[45],rx[64];size_t n;
    start(&s,&p);for(size_t i=0;i<sizeof(tx);i++)tx[i]=(uint8_t)(i*7+3);
    assert(btif_pio_begin(&s,tx,sizeof(tx),100,10000)==0);
    assert(btif_pio_step(&s,rx,sizeof(rx),&n,101)==0 && !n);
    assert(s.tx_written==16 && !s.tx_complete);
    assert(btif_pio_finish(&s,101)==BTIF_STATE);
    /* Full FIFO permits no write; exactly eight slots available below THRE. */
    assert(btif_pio_step(&s,rx,sizeof(rx),&n,102)==0 && s.tx_written==16);
    p.tx_fifo=8;assert(btif_pio_step(&s,rx,sizeof(rx),&n,103)==0);
    assert(s.tx_written==24 && p.tx_fifo==16);
    p.tx_fifo=0;assert(btif_pio_step(&s,rx,sizeof(rx),&n,104)==0);
    assert(s.tx_written==40 && !s.tx_complete);
    p.tx_fifo=0;assert(btif_pio_step(&s,rx,sizeof(rx),&n,105)==0);
    assert(s.tx_written==45 && !s.tx_complete);
    p.tx_fifo=0;assert(btif_pio_step(&s,rx,sizeof(rx),&n,106)==0 && s.tx_complete);
    assert(!memcmp(tx,p.tx,sizeof(tx)) && p.writes8==sizeof(tx));
    assert(btif_pio_finish(&s,107)==0 && !s.active);
}
static void receive_and_stream(void)
{
    struct btif_pio s;struct peripheral p;uint8_t tx[2054],rx[64];size_t n;
    start(&s,&p);for(size_t i=0;i<sizeof(tx);i++)tx[i]=(uint8_t)(i+19);
    assert(btif_pio_begin(&s,tx,sizeof(tx),0,100000)==0);
    for(size_t i=0;i<sizeof(p.rx);i++)p.rx[i]=(uint8_t)(i+7);
    unsigned now=1,total=0;
    while(!s.tx_complete || p.rx_read<p.rx_length) {
        memset(rx,0xcc,sizeof(rx));p.tx_fifo=0;
        /* No event belongs to this command before the final byte is sent. */
        if(s.tx_written==s.tx_length)p.rx_length=sizeof(p.rx);
        assert(btif_pio_step(&s,rx,sizeof(rx),&n,now++)==0 && n<=32);
        for(size_t i=0;i<n;i++)assert(rx[i]==(uint8_t)(total+i+7));
        for(size_t i=n;i<sizeof(rx);i++)assert(rx[i]==0xcc);
        total+=(unsigned)n;assert(now<1000);
    }
    assert(total==sizeof(p.rx) && s.rx_total==total);
    assert(p.tx_length==sizeof(tx) && !memcmp(tx,p.tx,sizeof(tx)));
    assert(btif_pio_finish(&s,now)==0);
    assert(btif_pio_begin(&s,NULL,0,now,1000)==0);
    p.rx_read=0;p.rx_length=5;
    assert(btif_pio_step(&s,rx,2,&n,now+1)==0 && n==2 && p.rx_read==2);
    assert(btif_pio_step(&s,rx,2,&n,now+2)==0 && n==2 && p.rx_read==4);
    assert(btif_pio_step(&s,rx,2,&n,now+3)==0 && n==1 && p.rx_read==5);
    assert(btif_pio_finish(&s,now+4)==0);
}
static void errors(void)
{
    struct btif_pio s;struct peripheral p;uint8_t tx[20]={0},rx[4];size_t n;
    for(unsigned i=0;i<7;i++) {
        start(&s,&p);assert(btif_pio_begin(&s,tx,sizeof(tx),100,1000)==0);
        unsigned a=p.accesses,w=p.writes8;
        if(i==0)p.accessible=0;
        if(i==1)p.regs[0x4c/4]|=1;
        if(i==2)p.regs[1]|=2;
        if(i==3)p.regs[0x60/4]|=0x80;
        uint64_t now=i==4?99:i==5?1100:101;
        if(i==6)s.polls=1000000;
        n=99;assert(btif_pio_step(&s,rx,sizeof(rx),&n,now)<0 && !n);
        assert(p.writes8==w && !s.active && !s.tx_complete);
        if(i==0 || i>=4)assert(p.accesses==a);
        a=p.accesses;
        assert(btif_pio_step(&s,rx,sizeof(rx),&n,now)<0 && p.accesses==a);
    }
    start(&s,&p);unsigned a=p.accesses;
    assert(btif_pio_begin(&s,NULL,1,0,1000)==BTIF_ARGUMENT);
    assert(btif_pio_begin(&s,tx,2055,0,1000)==BTIF_ARGUMENT);
    assert(btif_pio_begin(&s,tx,1,UINT64_MAX-9,1000)==BTIF_ARGUMENT);
    assert(btif_pio_begin(&s,tx,1,0,999)==BTIF_ARGUMENT && p.accesses==a);
    /* A nonadvancing clock cannot spin forever even when hardware stays idle. */
    assert(btif_pio_begin(&s,NULL,0,0,1000)==0);
    for(unsigned i=0;i<1000000;i++)assert(btif_pio_step(&s,rx,1,&n,0)==0);
    assert(btif_pio_step(&s,rx,1,&n,0)==BTIF_BUDGET);
    /* Old pending replies must not satisfy a new command, even when they
     * arrive in the gap between begin() and the first pump. */
    start(&s,&p);p.rx_length=1;
    assert(btif_pio_begin(&s,tx,1,0,1000)==BTIF_BUSY && !p.writes8 && !p.reads8);
    start(&s,&p);assert(btif_pio_begin(&s,tx,1,0,1000)==0);p.rx_length=1;
    assert(btif_pio_step(&s,rx,1,&n,1)==BTIF_BUSY && !p.writes8 && !p.reads8);
    start(&s,&p);assert(btif_pio_begin(&s,NULL,0,100,1000)==0);
    assert(btif_pio_step(&s,rx,1,&n,101)==0 && s.tx_complete);
    a=p.accesses;assert(btif_pio_finish(&s,1100)==BTIF_TIMEOUT && p.accesses==a);
    start(&s,&p);assert(btif_pio_begin(&s,NULL,0,100,1000)==0);
    assert(btif_pio_step(&s,rx,1,&n,101)==0 && s.tx_complete);
    a=p.accesses;assert(btif_pio_finish(&s,99)==BTIF_CLOCK && p.accesses==a);
}
int main(void)
{
    admission();fifo_progress();receive_and_stream();errors();
    puts("BTIF PIO: ownership, access widths, FIFO capacity, streaming, deadlines and sticky failures passed");
    return 0;
}
