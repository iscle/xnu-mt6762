/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdio.h>
#include "../../../../bsd/dev/mt6762_msdc_protocol.h"
enum {NONE,CMD_CRC,CMD_TIMEOUT,DATA_CRC,SHORT_DATA,NO_DONE,DROP_ACK,LOST_OWNER,BAD_STATUS,DATA_DONE_ERROR};
struct fixture {
    uint32_t cfg,sdc,irq,block,arg,command,fifo_pos;
    uint32_t dma,cq,queue,crypto,inten,busy;
    uint64_t time;
    unsigned reads,writes,commands,admitted,fault,data_active,ext_bad,time_mode,preempt,late_command,late_data;
    unsigned opcodes[32],count;
    uint8_t ext[512],sector[512];
};
static int admit(void *ctx)
{
    struct fixture *f=ctx;
    return !f->admitted || (f->fault==LOST_OWNER && f->command==0x02000891 && f->fifo_pos==512);
}
static uint32_t read32(void *ctx,uint32_t reg)
{
    struct fixture *f=ctx;f->reads++;
    switch(reg) {
    case 0:return f->cfg;
    case 0x30:return f->sdc;
    case 0x0c:
        if(f->fault==DATA_CRC && f->data_active && f->fifo_pos>=128)f->irq|=0x8000;
        /* Completion arrives while the owner is descheduled after a stale
         * not-ready read, before it can inspect the elapsed deadline. */
        if(f->late_command && f->irq==0x100) {
            f->late_command=0;f->time+=1000;return 0;
        }
        return f->irq;
    case 0x10:return f->inten;
    case 0x3c:return f->busy;
    case 0x9c:return f->dma;
    case 0x204:return f->queue;
    case 0x23c:return f->cq;
    case 0x670:return f->crypto;
    case 0x50:return f->block;
    case 0x40:return f->fault==BAD_STATUS?0xb00:0x900;
    case 0x14:
        if(!f->data_active)return 0;
        if(f->late_data && f->fifo_pos==128) {
            f->late_data=0;f->time+=1000;return 0;
        }
        if(f->fault==SHORT_DATA && f->fifo_pos>=256)return 0;
        return 512-f->fifo_pos>128?128:512-f->fifo_pos;
    case 0x1c: {
        assert(f->data_active && f->fifo_pos<=508);
        /* Another runnable thread can delay the PIO owner between FIFO reads.
         * The card still has data and has reported no hardware error. */
        if(f->preempt && f->fifo_pos==128)f->time+=1000;
        const uint8_t *bytes=f->command==0x02000888?f->ext:f->sector;
        uint32_t result=0;
        for(unsigned i=0;i<4;i++)result|=(uint32_t)bytes[f->fifo_pos++]<<(i*8);
        if(f->fifo_pos==512){f->data_active=0;if(f->fault!=NO_DONE)f->irq|=0x1000;
            if(f->fault==DATA_DONE_ERROR)f->irq|=0x8000;}
        return result;
    }
    default:assert(!"unexpected read register");return 0;
    }
}
static void write32(void *ctx,uint32_t reg,uint32_t value)
{
    struct fixture *f=ctx;f->writes++;
    switch(reg) {
    case 0x50:assert(value==1);f->block=value;break;
    case 0x38:f->arg=value;break;
    case 0x34:
        assert(value==0x8d || value==0x02000888 || value==0x02000891);
        f->command=value;f->commands++;f->opcodes[f->count++%32]=value&63;
        f->irq=f->fault==CMD_TIMEOUT?0:(f->fault==CMD_CRC?0x500:0x100);
        if(value!=0x8d){assert(f->block==1);f->fifo_pos=0;f->data_active=1;}
        break;
    case 0x0c:
        assert(!(value&~0x1700u));
        if(!(f->fault==DROP_ACK && (value&0x1000)))f->irq&=~value;
        break;
    default:assert(!"forbidden config/reset/DMA/card-write register operation");
    }
}
static uint64_t time_us(void *ctx)
{struct fixture *f=ctx;return f->time_mode==2?f->time--:f->time;}
static void delay_us(void *ctx,uint32_t n)
{struct fixture *f=ctx;if(!f->time_mode)f->time+=n;}
static void setup(struct fixture *f)
{
    memset(f,0,sizeof(*f));f->cfg=0x89;f->sdc=0x20000;f->crypto=4;f->admitted=1;
    f->ext[212]=8;f->ext[183]=2;f->ext[185]=2;f->ext[196]=0x56;
    for(unsigned i=0;i<512;i++)f->sector[i]=(uint8_t)(i*7+3);
}
static int initialize(struct mt6762_msdc *s,struct fixture *f)
{
    struct mt6762_msdc_io io={f,admit,read32,write32,time_us,delay_us};
    struct mt6762_msdc_config cfg={8,1,0x89,0x20000,100,200000000};
    return mt6762_msdc_init(s,&io,&cfg);
}
int main(void)
{
    struct fixture f;struct mt6762_msdc s={0};uint8_t output[512];
    setup(&f);assert(!initialize(&s,&f));
    assert(f.count==3 && f.opcodes[0]==13 && f.opcodes[1]==8 && f.opcodes[2]==13);
    memset(output,0xa5,sizeof(output));assert(!mt6762_msdc_read512(&s,7,output));
    assert(!memcmp(output,f.sector,512));assert(f.opcodes[3]==13 && f.opcodes[4]==17 && f.opcodes[5]==13);
    unsigned reads=f.reads,writes=f.writes;
    assert(mt6762_msdc_read512(&s,8,output)==MT6762_MSDC_ARGUMENT);
    assert(mt6762_msdc_read512(&s,UINT64_MAX,output)==MT6762_MSDC_ARGUMENT);
    assert(f.reads==reads && f.writes==writes && !s.faulted);
    assert(initialize(&s,&f)==MT6762_MSDC_FAULTED);
    setup(&f);memset(&s,0,sizeof(s));assert(!initialize(&s,&f));f.preempt=1;
    memset(output,0xa5,sizeof(output));assert(!mt6762_msdc_read512(&s,2,output));
    assert(!memcmp(output,f.sector,512) && !s.faulted);
    setup(&f);memset(&s,0,sizeof(s));assert(!initialize(&s,&f));f.late_data=1;
    memset(output,0xa5,sizeof(output));assert(!mt6762_msdc_read512(&s,2,output));
    assert(!memcmp(output,f.sector,512) && !s.faulted);
    setup(&f);memset(&s,0,sizeof(s));assert(!initialize(&s,&f));f.late_command=1;
    memset(output,0xa5,sizeof(output));assert(!mt6762_msdc_read512(&s,2,output));
    assert(!memcmp(output,f.sector,512) && !s.faulted);
    for(unsigned fault=CMD_CRC;fault<=DATA_DONE_ERROR;fault++) {
        setup(&f);memset(&s,0,sizeof(s));assert(!initialize(&s,&f));f.fault=fault;
        memset(output,0xa5,sizeof(output));assert(mt6762_msdc_read512(&s,2,output)<0);
        for(unsigned i=0;i<512;i++)assert(output[i]==0xa5);
        assert(s.faulted);reads=f.reads;writes=f.writes;
        assert(mt6762_msdc_read512(&s,2,output)==MT6762_MSDC_FAULTED);
        assert(f.reads==reads && f.writes==writes);
    }
    /* A broken time source must not defeat the iteration deadline, and a
     * backwards jump must fail immediately without exposing staged bytes. */
    for(unsigned mode=1;mode<=2;mode++) {
        setup(&f);memset(&s,0,sizeof(s));assert(!initialize(&s,&f));
        f.fault=CMD_TIMEOUT;f.time_mode=mode;f.time=1000;reads=f.reads;
        memset(output,0xa5,sizeof(output));
        assert(mt6762_msdc_read512(&s,2,output)==MT6762_MSDC_TIMEOUT);
        assert(s.faulted && f.reads-reads<200);
        for(unsigned i=0;i<512;i++)assert(output[i]==0xa5);
    }
    /* Every inherited-state failure must precede any register write. */
    for(unsigned test=0;test<10;test++) {
        setup(&f);memset(&s,0,sizeof(s));
        switch(test){case 0:f.admitted=0;break;case 1:f.cfg^=0x100;break;
        case 2:f.sdc^=0x100;break;case 3:f.irq=0x100;break;case 4:f.inten=1;break;
        case 5:f.busy=1;break;case 6:f.dma=1;break;case 7:f.cq=2;break;
        case 8:f.queue=1;break;case 9:f.crypto=0;break;}
        assert(initialize(&s,&f)<0 && !f.writes);
        if(!test)assert(!f.reads);
    }
    /* Actual EXT_CSD, not metadata alone, must confirm card state/capacity. */
    const unsigned offsets[]={15,179,183,185,212};
    for(unsigned i=0;i<sizeof(offsets)/sizeof(offsets[0]);i++) {
        setup(&f);memset(&s,0,sizeof(s));f.ext[offsets[i]]^=1;
        assert(initialize(&s,&f)==MT6762_MSDC_CARD && s.faulted);
    }
    setup(&f);memset(&s,0,sizeof(s));f.ext[196]=0x20; /*1.2V-only HS200*/
    assert(initialize(&s,&f)==MT6762_MSDC_CARD && s.faulted);
    setup(&f);memset(&s,0,sizeof(s));assert(!initialize(&s,&f));writes=f.writes;
    assert(mt6762_msdc_data512(&s,24,0,output)==MT6762_MSDC_ARGUMENT && f.writes==writes);
    puts("PASS: inherited MSDC admission, EXT_CSD proof, complete512-byte PIO, bounds, terminal faults and unchanged failed output");
    return 0;
}
