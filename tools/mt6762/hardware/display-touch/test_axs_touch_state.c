/* Synthetic protocol/state-machine tests; no physical packet captures used. */
#include "axs_touch_state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct event { unsigned type,id,x,y; };
struct output { struct event events[128]; unsigned n; };
static void emit(void *p,unsigned t,unsigned id,unsigned x,unsigned y)
{
    struct output *o=p; assert(o->n<128);
    o->events[o->n++]=(struct event){t,id,x,y};
}
static void contact(uint8_t *p,unsigned index,unsigned id,unsigned event,unsigned x,unsigned y)
{
    uint8_t *r=p+2+6*index;
    r[0]=(uint8_t)((event<<6)|(x>>8));r[1]=(uint8_t)x;
    r[2]=(uint8_t)((id<<4)|(y>>8));r[3]=(uint8_t)y;r[4]=63;r[5]=0x90;
}
int main(void)
{
    struct axs_state s; struct output o={0}; uint8_t p[32]={0,1};
    assert(axs_state_init(&s,384,854,100,emit,&o)==0);
    contact(p,0,0,0,0,0);
    assert(axs_state_feed(&s,p,32,1)==1 && o.n==1 && o.events[0].type==AXS_DOWN);
    assert(axs_state_feed(&s,p,32,2)==1 && o.n==1); /* repeated positions suppressed */
    contact(p,0,0,2,384,854);
    assert(axs_state_feed(&s,p,32,3)==1 && o.n==2);
    assert(o.events[1].type==AXS_MOVE && o.events[1].x==65535 && o.events[1].y==65535);
    contact(p,0,0,1,10,10);
    assert(axs_state_feed(&s,p,32,4)==1 && o.n==3 && !s.active);
    assert(o.events[2].type==AXS_UP && o.events[2].x==65535); /* last position */
    p[1]=5;
    for(unsigned i=0;i<5;i++)contact(p,i,i,2,192,427);
    assert(axs_state_feed(&s,p,32,5)==1 && s.active==31 && o.n==8);
    assert(o.events[7].x==32767 && o.events[7].y==32767);
    p[1]=1;contact(p,0,4,2,192,427);
    assert(axs_state_feed(&s,p,32,6)==1 && s.active==16 && o.n==12); /* four missing UPs */
    p[1]=2;contact(p,1,4,0,1,1);
    assert(axs_state_feed(&s,p,32,7)==-1 && !s.active && o.n==13); /* duplicate rejects atomically */
    assert(o.events[12].type==AXS_UP);
    p[1]=1;contact(p,0,0,0,1,1);assert(axs_state_feed(&s,p,32,8)==1);
    p[1]=0x11;assert(axs_state_feed(&s,p,32,9)==-1 && !s.active);
    p[1]=1;assert(axs_state_feed(&s,p,32,10)==1);
    assert(axs_state_feed(&s,p,31,11)==-1 && !s.active);
    assert(axs_state_feed(&s,p,32,12)==1);
    p[0]=0xff;assert(axs_state_feed(&s,p,32,13)==0 && s.active);
    assert(axs_state_expire(&s,111)==0 && s.active);
    assert(axs_state_expire(&s,112)==1 && !s.active); /* no packets: must release */
    unsigned before=o.n;assert(axs_state_expire(&s,113)==0 && o.n==before);
    p[0]=0;assert(axs_state_feed(&s,p,32,114)==1);
    assert(axs_state_feed(&s,p,32,113)==-1 && !s.active); /* clock regression */
    contact(p,0,0,0,385,0);before=o.n;
    assert(axs_state_feed(&s,p,32,115)==-1 && !s.active && o.n==before);
    contact(p,0,0,3,0,0);assert(axs_state_feed(&s,p,32,116)==-1);
    contact(p,0,0,0,0,0);assert(axs_state_feed(&s,p,32,117)==1);
    p[1]=15;assert(axs_state_feed(&s,p,32,118)==-1 && !s.active);
    p[1]=1;assert(axs_state_feed(&s,p,32,119)==1);
    p[1]=0;assert(axs_state_feed(&s,p,32,120)==1 && !s.active);
    p[1]=1;assert(axs_state_feed(&s,p,32,121)==1);
    axs_state_release_all(&s);assert(!s.active);
    assert(axs_state_feed(&s,NULL,32,122)==-1);
    puts("AXS state tracker synthetic tests passed");
}
