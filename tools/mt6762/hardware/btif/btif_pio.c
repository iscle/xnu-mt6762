#include "btif_pio.h"

enum { DATA=0, IER=4, IIR=8, FAKELCR=12, LSR=20,
       DMA_EN=0x4c, TRI_LVL=0x60, HANDSHAKE=0x6c };
enum { MAX_TX=2054, MAX_RX_STEP=32, MAX_POLLS=1000000 };

static int fail(struct btif_pio *s,int e)
{
    if(s) { s->error=e; s->active=0; s->tx_complete=0; }
    return e;
}
static uint32_t rd(struct btif_pio *s,unsigned r)
{ return s->io.read32(s->io.context,r); }
static void wr(struct btif_pio *s,unsigned r,uint32_t v)
{ s->io.write32(s->io.context,r,v); }
static int accessible(struct btif_pio *s)
{ return s->io.ready(s->io.context)==1; }
static int config(struct btif_pio *s)
{
    /* No access after a failed always-on accessibility check. */
    if(!accessible(s)) return fail(s,BTIF_OWNERSHIP);
    if((rd(s,DMA_EN)&7)!=4 || (rd(s,IER)&3)!=1 ||
       (rd(s,TRI_LVL)&255)!=0x18 || !(rd(s,HANDSHAKE)&1) ||
       rd(s,FAKELCR)!=0) return fail(s,BTIF_CONFIG);
    return BTIF_OK;
}
int btif_pio_init(struct btif_pio *s,const struct btif_pio_io *io,
                  const struct btif_pio_grant *g)
{
    if(!s || !io || !g) return BTIF_ARGUMENT;
    /* A failed or already initialized instance requires explicit teardown by
     * its owner; this function is not an implicit peripheral reset. */
    if(s->initialized || s->active || s->error) return BTIF_STATE;
    if(g->enabled!=1) return fail(s,BTIF_DISABLED);
    if(g->exclusive!=1 || g->irq_masked!=1 || g->apdma_idle!=1)
        return fail(s,BTIF_OWNERSHIP);
    if(!io->ready || !io->read32 || !io->write32 || !io->read8 || !io->write8)
        return fail(s,BTIF_ARGUMENT);
    s->io=*io;
    if(!accessible(s)) return fail(s,BTIF_OWNERSHIP);
    uint32_t dma=rd(s,DMA_EN),status=rd(s,LSR),ier=rd(s,IER);
    if((dma&3) || (status&0x41)!=0x40 || (ier&2))
        return fail(s,BTIF_BUSY);
    /* The cold owner has already made both APDMA channels idle. Preserve
     * undocumented bits; do not clear a live DMA-enable bit to seize it. */
    wr(s,IER,ier&~3u);
    wr(s,FAKELCR,0);
    wr(s,HANDSHAKE,rd(s,HANDSHAKE)|1);
    wr(s,TRI_LVL,(rd(s,TRI_LVL)&~255u)|0x18);
    wr(s,DMA_EN,dma|4);
    wr(s,IER,(ier&~3u)|1);
    if(config(s)) return s->error;
    if((rd(s,LSR)&0x41)!=0x40) return fail(s,BTIF_BUSY);
    s->initialized=1;
    return BTIF_OK;
}
int btif_pio_begin(struct btif_pio *s,const uint8_t *tx,size_t length,
                   uint64_t now,uint64_t timeout)
{
    if(!s) return BTIF_ARGUMENT;
    if(s->error) return s->error;
    if(!s->initialized || s->active) return BTIF_STATE;
    if((length && !tx) || length>MAX_TX || timeout<1000 || timeout>10000000 ||
       now>UINT64_MAX-timeout) return BTIF_ARGUMENT;
    if(now<s->last_us) return fail(s,BTIF_CLOCK);
    if(config(s)) return s->error;
    /* Reject unsolicited bytes before a new command; otherwise a queued
     * old reply could satisfy a query that has not reached the device. */
    uint32_t status=rd(s,LSR);
    if(!(status&0x40) || (length && (status&1))) return fail(s,BTIF_BUSY);
    s->tx=tx; s->tx_length=length; s->tx_written=0;
    s->last_us=now; s->deadline_us=now+timeout; s->polls=0; s->rx_total=0;
    s->tx_complete=0; s->active=1;
    return BTIF_OK;
}
int btif_pio_step(struct btif_pio *s,uint8_t *rx,size_t capacity,
                  size_t *received,uint64_t now)
{
    if(received) *received=0;
    if(!s || !rx || !capacity || !received) return BTIF_ARGUMENT;
    if(s->error) return s->error;
    if(!s->initialized || !s->active) return BTIF_STATE;
    if(now<s->last_us) return fail(s,BTIF_CLOCK);
    s->last_us=now;
    if(now>=s->deadline_us) return fail(s,BTIF_TIMEOUT);
    if(++s->polls>MAX_POLLS) return fail(s,BTIF_BUDGET);
    if(config(s)) return s->error;
    if(s->tx_written<s->tx_length && (rd(s,IIR)&0x44))
        return fail(s,BTIF_BUSY); /* Unsolicited or premature response. */
    size_t n=0,limit=capacity<MAX_RX_STEP?capacity:MAX_RX_STEP;
    /* Exact shipped IRQ handler uses IIR0x44 for RX/timeout and byte RBR. */
    while(n<limit && (rd(s,IIR)&0x44)) rx[n++]=s->io.read8(s->io.context,DATA);
    uint32_t status=rd(s,LSR);
    size_t room=(status&0x40)?16:(status&0x20)?8:0;
    size_t left=s->tx_length-s->tx_written;
    if(room>left) room=left;
    for(size_t i=0;i<room;i++)
        s->io.write8(s->io.context,DATA,s->tx[s->tx_written++]);
    /* Re-read after the last write; prior TEMT cannot prove completion. */
    s->tx_complete=s->tx_written==s->tx_length && (rd(s,LSR)&0x40)!=0;
    s->rx_total+=(uint32_t)n;
    *received=n;
    return BTIF_OK;
}
int btif_pio_finish(struct btif_pio *s,uint64_t now)
{
    if(!s) return BTIF_ARGUMENT;
    if(s->error) return s->error;
    if(!s->active || !s->tx_complete) return BTIF_STATE;
    if(now<s->last_us) return fail(s,BTIF_CLOCK);
    if(now>=s->deadline_us) return fail(s,BTIF_TIMEOUT);
    s->last_us=now;
    if(config(s)) return s->error;
    if(!(rd(s,LSR)&0x40)) return fail(s,BTIF_BUSY);
    s->active=0; s->tx=NULL; s->tx_length=0;
    return BTIF_OK;
}
