#include "wmt_protocol.h"
static const uint8_t query[]={1,4,1,0,4};
static const uint8_t set_full[]={1,4,5,0,3,0xdb,0x0e,0x68,1};
static const uint8_t default_event[]={2,4,6,0,0,4,0x11,0,0,0};
static const uint8_t set_event[]={2,4,2,0,0,3};
static const uint8_t full_event[]={2,4,6,0,0,4,0xdb,0x0e,0x68,1};
static int fail(struct cw_session *s,int e) { s->error=e;s->phase=CW_FAILED;return e; }
uint16_t cw_crc16(const uint8_t *p,size_t n) {
 uint16_t crc=0;size_t i;unsigned b;
 for(i=0;i<n;i++){crc^=p[i];for(b=0;b<8;b++)crc=(crc>>1)^((crc&1)?0xa001:0);}
 return crc;
}
void cw_init(struct cw_session *s,unsigned enabled) {
 size_t i;uint8_t *p=(uint8_t *)s;if(!s)return;
 for(i=0;i<sizeof(*s);i++)p[i]=0;
 s->phase=enabled==1?CW_NEW:CW_OFF;s->mode=CW_BTIF_MANDATORY;s->txack=7;
}
int cw_poll(struct cw_session *s,uint64_t now) {
 if(!s)return CW_ARGUMENT;
 if(s->phase==CW_OFF)return CW_DISABLED;
 if(s->error)return s->error;
 if(now<s->last_us)return fail(s,CW_CLOCK);
 s->last_us=now;
 if(s->active){
  if(now>=s->deadline_us)return fail(s,CW_TIMEOUT);
  if(++s->polls>CW_POLL_MAX)return fail(s,CW_BUDGET);
 }
 return CW_OK;
}
int cw_command(struct cw_session *s,enum cw_command cmd,uint64_t now,
 uint64_t timeout,uint8_t *out,size_t capacity,size_t *written) {
 const uint8_t *p=query;size_t n=sizeof(query),i;uint16_t crc;int r;
 if(!s||!out||!written)return CW_ARGUMENT;
 if((r=cw_poll(s,now)))return r;
 if(timeout<1000||timeout>10000000||now>UINT64_MAX-timeout)return CW_ARGUMENT;
 if(s->used||s->wused||s->active||s->ack_pending)return CW_STATE;
 if(cmd==CW_QUERY_DEFAULT&&s->phase==CW_NEW){}
 else if(cmd==CW_SET_FULL&&s->phase==CW_DEFAULT_VERIFIED&&s->pda_ready){p=set_full;n=sizeof(set_full);}
 else if(cmd==CW_QUERY_FULL&&s->phase==CW_FULL){}
 else return CW_STATE;
 if(capacity<n+6)return CW_ARGUMENT;
 out[0]=s->mode==CW_BTIF_FULL?(uint8_t)(0x80|(s->txseq<<3)|s->txack):0x80;
 out[1]=0x40;out[2]=(uint8_t)n;
 out[3]=s->mode==CW_BTIF_FULL?(uint8_t)(out[0]+out[1]+out[2]):0;
 for(i=0;i<n;i++)out[4+i]=p[i];
 crc=s->mode==CW_BTIF_FULL?cw_crc16(p,n):0;
 out[4+n]=(uint8_t)crc;out[5+n]=(uint8_t)(crc>>8);*written=n+6;
 s->phase=cmd==CW_QUERY_DEFAULT?CW_WAIT_DEFAULT:cmd==CW_SET_FULL?CW_WAIT_SET:CW_WAIT_FULL;
 s->active=1;s->deadline_us=now+timeout;s->polls=0;s->tx_acked=0;s->event_seen=0;
 return CW_OK;
}
int cw_attest_pda_patch_reset(struct cw_session *s,uint64_t now) {
 int r;if((r=cw_poll(s,now)))return r;
 if(s->phase!=CW_DEFAULT_VERIFIED||s->active||s->used||s->wused)return CW_STATE;
 s->pda_ready=1;return CW_OK;
}
int cw_enter_full(struct cw_session *s,uint64_t now) {
 int r;if((r=cw_poll(s,now)))return r;
 if(s->phase!=CW_SWITCH_WAIT||s->used||s->wused||now-s->switch_us<10000)return CW_STATE;
 s->mode=CW_BTIF_FULL;s->phase=CW_FULL;s->active=0;
 s->rxseq=0;s->txseq=0;s->txack=7;s->ack_pending=0;
 return CW_OK;
}
static void complete_full(struct cw_session *s) {
 if(s->phase==CW_WAIT_FULL&&s->event_seen&&s->tx_acked){
  s->phase=CW_OPTIONS_VERIFIED;s->active=0;
 }
}
static int event(struct cw_session *s) {
 const uint8_t *expected;size_t n,i;
 if(s->phase==CW_WAIT_DEFAULT){expected=default_event;n=sizeof(default_event);}
 else if(s->phase==CW_WAIT_SET){expected=set_event;n=sizeof(set_event);}
 else if(s->phase==CW_WAIT_FULL&&!s->event_seen){expected=full_event;n=sizeof(full_event);}
 else return fail(s,CW_EVENT);
 if(s->wused<5||s->wmt[0]!=2||s->wmt[1]!=4)return fail(s,CW_EVENT);
 if(s->wmt[4])return fail(s,CW_STATUS);
 if(s->wused!=n)return fail(s,CW_EVENT);
 for(i=0;i<n;i++)if(s->wmt[i]!=expected[i])return fail(s,CW_EVENT);
 s->events++;
 if(s->phase==CW_WAIT_DEFAULT){s->phase=CW_DEFAULT_VERIFIED;s->active=0;}
 else if(s->phase==CW_WAIT_SET){s->phase=CW_SWITCH_WAIT;s->switch_us=s->last_us;
  /* Existing command deadline also bounds the host-mode transition. */
 }else{s->event_seen=1;complete_full(s);}
 return CW_OK;
}
static int wmt_bytes(struct cw_session *s,const uint8_t *p,size_t n) {
 size_t i;int r;
 for(i=0;i<n;i++){
  if(s->wused>=CW_WMT_MAX)return fail(s,CW_LENGTH);
  s->wmt[s->wused++]=p[i];
  if(s->wused==4){
   s->wneed=4u+s->wmt[2]+((uint32_t)s->wmt[3]<<8);
   if(s->wneed<5||s->wneed>CW_WMT_MAX)return fail(s,CW_LENGTH);
  }
  if(s->wneed&&s->wused==s->wneed){
   if((r=event(s)))return r;
   s->wused=0;s->wneed=0;
  }
 }
 return CW_OK;
}
static int packet(struct cw_session *s) {
 uint8_t *p=s->packet,ack=p[0]&7,seq=(p[0]>>3)&7;
 size_t n=((p[1]&15u)<<8)|p[2];uint16_t crc;int r;
 if(n){
  crc=(uint16_t)(p[4+n]|((uint16_t)p[5+n]<<8));
  if(crc!=(s->mode==CW_BTIF_FULL?cw_crc16(p+4,n):0))return fail(s,CW_CRC);
 }
 if(s->mode==CW_BTIF_FULL){
  /* One outstanding command, no retries or recovery from unknown history. */
  if(ack==s->txseq)s->tx_acked=1;
  else if(ack!=((s->txseq+7)&7)||s->tx_acked)return fail(s,CW_ACK);
  if(n){
   if(seq!=s->rxseq)return fail(s,CW_SEQUENCE);
   s->txack=seq;s->rxseq=(uint8_t)((seq+1)&7);
   s->ack_pending=1;s->ack_value=seq;
  }else{s->acknowledgements++;complete_full(s);}
 }
 s->packets++;
 if(n&&(r=wmt_bytes(s,p+4,n)))return r;
 return CW_OK;
}
int cw_feed(struct cw_session *s,const uint8_t *p,size_t n,uint64_t now) {
 size_t i;unsigned len,type;int r;
 if(!s||(!p&&n))return CW_ARGUMENT;
 if((r=cw_poll(s,now)))return r;
 if(n>65536)return fail(s,CW_LENGTH); /* bounded work per call */
 for(i=0;i<n;i++){
  if(!s->active)return fail(s,CW_STATE);
  if(!s->used&&s->mode==CW_BTIF_FULL&&p[i]==0x55){
   if(++s->delimiters>2)return fail(s,CW_HEADER);
   continue;
  }
  if(s->used>=sizeof(s->packet))return fail(s,CW_LENGTH);
  s->packet[s->used++]=p[i];
  if(s->used==1){
   if((s->mode==CW_BTIF_MANDATORY&&p[i]!=0x80)||
      (s->mode==CW_BTIF_FULL&&(p[i]&0xc0)!=0x80))return fail(s,CW_HEADER);
   s->delimiters=0;
  }
  if(s->used==4){
   len=((s->packet[1]&15u)<<8)|s->packet[2];type=(s->packet[1]>>4)&7;
   if(s->packet[1]&0x80)return fail(s,CW_HEADER); /* NAK/recovery unsupported */
   if(len>CW_STP_MAX||(s->mode==CW_BTIF_MANDATORY&&len>=2000))return fail(s,CW_LENGTH);
   if((len&&type!=4)||(!len&&(type||s->mode!=CW_BTIF_FULL)))return fail(s,CW_CHANNEL);
   if(s->packet[3]!=(s->mode==CW_BTIF_FULL?
       (uint8_t)(s->packet[0]+s->packet[1]+s->packet[2]):0))return fail(s,CW_CHECKSUM);
   s->need=len?len+6:4;
  }
  if(s->need&&s->used==s->need){
   if((r=packet(s)))return r;
   s->used=0;s->need=0;
  }
 }
 return CW_OK;
}
int cw_take_ack(struct cw_session *s,uint8_t out[4]) {
 if(!s||!out)return CW_ARGUMENT;
 if(s->error)return s->error;
 if(s->mode!=CW_BTIF_FULL||!s->ack_pending)return CW_STATE;
 out[0]=(uint8_t)(0x80|s->ack_value);out[1]=0;out[2]=0;out[3]=out[0];
 s->ack_pending=0;return CW_OK;
}
