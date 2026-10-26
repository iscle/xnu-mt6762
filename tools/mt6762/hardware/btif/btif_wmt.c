#include "btif_wmt.h"
static int failed(struct btif_wmt_query *s,int transport,int protocol)
{
    s->phase=BTIF_WMT_FAILED;
    s->transport_error=transport;s->protocol_error=protocol;
    return -1;
}
int btif_wmt_start(struct btif_wmt_query *s,const struct btif_pio_io *io,
                   const struct btif_pio_grant *grant,uint64_t now,uint64_t timeout)
{
    int r;size_t written=0;
    if(!s || !io || !grant || s->phase!=BTIF_WMT_NEW) return -1;
    /* Validate the whole command before changing the peripheral. */
    cw_init(&s->protocol,grant->enabled);
    r=cw_command(&s->protocol,CW_QUERY_DEFAULT,now,timeout,s->tx,sizeof(s->tx),&written);
    if(r) return failed(s,0,r);
    r=btif_pio_init(&s->transport,io,grant);
    if(r) return failed(s,r,0);
    r=btif_pio_begin(&s->transport,s->tx,written,now,timeout);
    if(r) return failed(s,r,0);
    s->phase=BTIF_WMT_QUERY;
    return 0;
}
int btif_wmt_step(struct btif_wmt_query *s,uint64_t now)
{
    int r;size_t n=0;
    if(!s || s->phase!=BTIF_WMT_QUERY) return -1;
    r=cw_poll(&s->protocol,now);
    if(r) return failed(s,0,r);
    r=btif_pio_step(&s->transport,s->rx,sizeof(s->rx),&n,now);
    if(r) return failed(s,r,0);
    if(n) {
        r=cw_feed(&s->protocol,s->rx,n,now);
        if(r) return failed(s,0,r);
    }
    if(s->protocol.phase==CW_DEFAULT_VERIFIED && s->transport.tx_complete) {
        r=btif_pio_finish(&s->transport,now);
        if(r) return failed(s,r,0);
        s->phase=BTIF_WMT_DEFAULT_OPTIONS;
    }
    return 0;
}
