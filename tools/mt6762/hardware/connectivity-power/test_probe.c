/* SPDX-License-Identifier: MIT -- executes the actual passive collector. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../physical/connectivity_probe.h"
struct mock {
    uint64_t now,step,jump;
    unsigned reads,barriers,times;
    int fail_at,gated_pass,wrong_family_pass,tamper;
    struct mt6762_connectivity_record *record;
};
static int sample(struct mock *m,unsigned bus,uint32_t address,uint32_t *value)
{
    unsigned index=m->reads%40,pass=m->reads/40;
    assert(bus==(index>=21));
    assert(address==(bus?mt6762_connectivity_pmic_regs[index-21]:mt6762_connectivity_ap_regs[index]));
    assert(!(address>=0x18000000 && address<0x19000000));
    *value=bus?(address^0x1234):(address^0x12345678);
    if(address==0x0008)*value=(int)pass==m->wrong_family_pass?0x5801:0x5700+pass;
    if(address==0x10001090)*value=(int)pass==m->gated_pass?2:0;
    if(m->tamper && index+1<40)m->record->entries[index+1].address=0x18000000;
    m->now+=m->jump;
    return (int)m->reads++==m->fail_at?-77:0;
}
static int ap(void *p,uint32_t address,uint32_t *value)
{return sample(p,0,address,value);}
static int pmic(void *p,uint16_t address,uint16_t *value)
{uint32_t v;int e=sample(p,1,address,&v);*value=(uint16_t)v;return e;}
static uint64_t ticks(void *p)
{struct mock *m=p;uint64_t v=m->now;m->now+=m->step;m->times++;return v;}
static void barrier(void *p){((struct mock *)p)->barriers++;}
static const uint8_t identity[32]={1,2,3,4};
static struct mt6762_connectivity_record record;
static struct mt6762_connectivity_io setup(struct mock *m)
{
    *m=(struct mock){.step=1,.fail_at=-1,.gated_pass=-1,.wrong_family_pass=-1,.record=&record};
    memset(&record,0xa5,sizeof(record));
    return (struct mt6762_connectivity_io){m,ap,pmic,ticks,barrier,13000000,250000};
}
int main(int argc,char **argv)
{
    struct mock m;struct mt6762_connectivity_io io=setup(&m);
    assert(mt6762_connectivity_capture(&io,&record,identity,0)==1);
    assert(!m.reads && !m.times && !m.barriers && record.state==1);
    assert(mt6762_connectivity_capture(NULL,&record,identity,0)==1);
    for(unsigned invalid=0;invalid<9;invalid++) {
        io=setup(&m);const uint8_t *id=identity;int enabled=1;
        switch(invalid) {
        case 0:io.read_ap32=NULL;break;case 1:io.read_pmic16=NULL;break;
        case 2:io.ticks=NULL;break;case 3:io.barrier=NULL;break;
        case 4:io.budget_us=0;break;case 5:io.budget_us=1000001;break;
        case 6:id=NULL;break;case 7:enabled=-1;break;case 8:enabled=2;break;
        }
        assert(mt6762_connectivity_capture(&io,&record,id,enabled)==-1);
        assert(!m.reads && !m.times && !m.barriers);
    }
    io=setup(&m);io.counter_hz=0;
    assert(mt6762_connectivity_capture(&io,&record,identity,1)==-4 && !m.reads && !m.times);
    for(int failed=0;failed<80;failed++) {
        io=setup(&m);m.fail_at=failed;
        assert(mt6762_connectivity_capture(&io,&record,identity,1)==-2);
        assert(m.reads==(unsigned)failed+1 && record.state==4 && record.state_inverse==~4u);
        assert(record.pass==(unsigned)failed/40+1 && record.index==(unsigned)failed%40);
        assert(record.transport_error==-77 && record.entries[failed%40].error[failed/40]==-77);
        assert(!(record.entries[failed%40].valid&(1u<<(failed/40))));
        assert(record.entries[failed%40].value[failed/40]==0);
        for(unsigned p=0;p<2;p++)for(unsigned i=0;i<40;i++) {
            unsigned n=p*40+i;
            if(n<(unsigned)failed)assert(record.entries[i].valid&(1u<<p));
            if(n>(unsigned)failed)assert(record.entries[i].error[p]==INT32_MIN && !(record.entries[i].valid&(1u<<p)));
        }
    }
    for(int pass=0;pass<2;pass++) {
        io=setup(&m);m.gated_pass=pass;
        assert(mt6762_connectivity_capture(&io,&record,identity,1)==-5);
        assert(m.reads==(unsigned)pass*40+16 && record.index==16 && record.transport_error==0);
    }
    for(int pass=0;pass<2;pass++) {
        io=setup(&m);m.wrong_family_pass=pass;
        assert(mt6762_connectivity_capture(&io,&record,identity,1)==-6);
        assert(m.reads==(unsigned)pass*40+22 && record.index==21 && record.transport_error==0);
        assert(record.entries[21].value[pass]==0x5801 && (record.entries[21].valid&(1u<<pass)));
        assert(!record.entries[21].error[pass] && record.entries[22].error[pass]==INT32_MIN);
    }
    io=setup(&m);io.budget_us=1;m.step=14;
    assert(mt6762_connectivity_capture(&io,&record,identity,1)==-3 && !m.reads);
    io=setup(&m);io.budget_us=1;m.jump=13;
    assert(mt6762_connectivity_capture(&io,&record,identity,1)==-3 && m.reads==1);
    assert(record.entries[0].valid==1 && record.entries[0].error[0]==0);
    io=setup(&m);m.now=UINT64_MAX-50;
    assert(!mt6762_connectivity_capture(&io,&record,identity,1) && m.reads==80);
    io=setup(&m);m.step=0;
    assert(!mt6762_connectivity_capture(&io,&record,identity,1) && m.reads==80);
    io=setup(&m);m.tamper=1;
    assert(!mt6762_connectivity_capture(&io,&record,identity,1) && m.reads==80);
    /* Even malicious alteration of retained addresses never alters requests. */
    io=setup(&m);assert(!mt6762_connectivity_capture(&io,&record,identity,1));
    for(unsigned i=0;i<40;i++)assert(record.entries[i].valid==3 && !record.entries[i].error[0] && !record.entries[i].error[1]);
    for(unsigned i=0;i<sizeof(record.reserved);i++)assert(!record.reserved[i]);
    assert(!memcmp(record.identity,identity,32) && record.size==4096 && record.version==1);
    if(argc>=2) {FILE *f=fopen(argv[1],"wb");assert(f);assert(fwrite(&record,1,sizeof(record),f)==sizeof(record));assert(!fclose(f));}
    if(argc>=3) {
        io=setup(&m);m.fail_at=62;assert(mt6762_connectivity_capture(&io,&record,identity,1)==-2);
        FILE *f=fopen(argv[2],"wb");assert(f);assert(fwrite(&record,1,sizeof(record),f)==sizeof(record));assert(!fclose(f));
    }
    if(argc>=4) {
        io=setup(&m);m.wrong_family_pass=0;assert(mt6762_connectivity_capture(&io,&record,identity,1)==-6);
        FILE *f=fopen(argv[3],"wb");assert(f);assert(fwrite(&record,1,sizeof(record),f)==sizeof(record));assert(!fclose(f));
    }
    if(argc>=5) {
        io=setup(&m);m.now=UINT64_MAX-50;assert(!mt6762_connectivity_capture(&io,&record,identity,1));
        FILE *f=fopen(argv[4],"wb");assert(f);assert(fwrite(&record,1,sizeof(record),f)==sizeof(record));assert(!fclose(f));
    }
    if(argc>=6) {
        io=setup(&m);assert(mt6762_connectivity_capture(&io,&record,identity,0)==1);
        FILE *f=fopen(argv[5],"wb");assert(f);assert(fwrite(&record,1,sizeof(record),f)==sizeof(record));assert(!fclose(f));
    }
    puts("connectivity collector: disabled,80 fault sites, clock gates, deadlines/wrap/frozen timer, fixed addresses and complete record PASS");
    return 0;
}
