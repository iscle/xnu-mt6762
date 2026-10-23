#include <assert.h>
#include <stdio.h>
#include "../../../../bsd/dev/mt6762_bif_protocol.h"
struct fake {
    uint16_t tdet,raw[3];
    unsigned active,reads,operations,fail_at,dead,requests,tdet_writes,commit_failed_write;
    unsigned fault_channel,timeout,stale,rail,unexpected,drop_clear,drop_restore;
    unsigned delays;
};
static int io_fault(struct fake *f)
{f->operations++;if(f->operations==f->fail_at)f->dead=1;return f->dead;}
static int read16(void *ctx,uint16_t address,uint16_t *value)
{
    struct fake *f=ctx;if(io_fault(f))return -1;
    if(address==0x1236) {*value=f->tdet;return 0;}
    unsigned channel=address==0x108a?1:address==0x108e?3:address==0x109e?11:99;
    assert(channel==f->active);
    unsigned idx=channel==1?0:channel==3?1:2;
    int fault=f->fault_channel==channel;
    f->reads++;
    if(fault && f->unexpected && f->reads==1)f->tdet^=f->unexpected==2?2:0x10;
    if(fault && f->stale) {*value=0x8000|f->raw[idx];return 0;}
    if(f->reads==1 || (fault && f->timeout)) {*value=0;return 0;}
    *value=0x8000|((fault && f->rail)?0:f->raw[idx]);return 0;
}
static int write16(void *ctx,uint16_t address,uint16_t value)
{
    struct fake *f=ctx;
    if(io_fault(f)) {
        if(f->operations==f->fail_at && f->commit_failed_write && address==0x1236) {
            f->tdet=value;f->tdet_writes++;
        }
        return -1;
    }
    if(address==0x1236) {
        f->tdet_writes++;
        if((!(value&2) && f->drop_clear) || ((value&2) && f->drop_restore))return 0;
        f->tdet=value;return 0;
    }
    assert(address==0x110e);
    assert(value==2 || value==8 || value==2048);
    f->active=value==2?1:value==8?3:11;f->reads=0;f->requests++;return 0;
}
static void delay_us(void *ctx,unsigned us) {((struct fake *)ctx)->delays+=us;}
static struct mt6762_bif_transport transport(struct fake *f)
{
    struct mt6762_bif_transport t={{f,read16,write16,delay_us},f->tdet,0,0};
    f->raw[0]=26700;f->raw[1]=1400;f->raw[2]=4089;return t;
}
static void failure_stays(struct fake *f,struct mt6762_bif_transport *t,struct mt6762_bif_pair *p)
{
    assert(t->fault && p->ntc_raw==123 && p->bif_raw==456);
    unsigned before=f->operations;
    assert(mt6762_bif_capture(t,p));assert(f->operations==before);
}
int main(void)
{
    unsigned success_operations=0;
    for(unsigned initial=4;initial<=6;initial+=2) {
        struct fake f={.tdet=initial};struct mt6762_bif_transport t=transport(&f);
        struct mt6762_bif_pair p={123,456};
        assert(!mt6762_bif_capture(&t,&p));assert(f.tdet==initial);
        assert(p.ntc_raw==1400 && p.bif_raw==4089 && !t.fault && !t.restoration_unknown);
        assert(f.tdet_writes==(initial==6?2:0) && f.requests==2);
        success_operations=f.operations;
    }
    /* A persistent transport failure at every actual I/O boundary. */
    for(unsigned n=1;n<=success_operations;n++) {
        struct fake f={.tdet=6,.fail_at=n};struct mt6762_bif_transport t=transport(&f);
        struct mt6762_bif_pair p={123,456};assert(mt6762_bif_capture(&t,&p));
        failure_stays(&f,&t,&p);
        if(f.tdet==4)assert(t.restoration_unknown);
        assert(f.tdet_writes<=2);
    }
    /* A wrapper can fail after the PMIC accepted the write: state is unknown
     * until independent readback succeeds, even when the fake knows it. */
    for(unsigned n=6;n<=12;n+=6) {
        struct fake f={.tdet=6,.fail_at=n,.commit_failed_write=1};
        struct mt6762_bif_transport t=transport(&f);struct mt6762_bif_pair p={123,456};
        assert(mt6762_bif_capture(&t,&p));failure_stays(&f,&t,&p);
        assert(t.restoration_unknown && f.tdet==(n==6?4:6));
    }
    for(unsigned channel=3;channel<=11;channel+=8)for(unsigned kind=0;kind<3;kind++) {
        struct fake f={.tdet=6,.fault_channel=channel};
        if(kind==0)f.timeout=1;
        if(kind==1)f.stale=1;
        if(kind==2)f.rail=1;
        struct mt6762_bif_transport t=transport(&f);struct mt6762_bif_pair p={123,456};
        assert(mt6762_bif_capture(&t,&p));failure_stays(&f,&t,&p);
        assert(f.tdet==6 && !t.restoration_unknown && f.delays<=64200);
        assert(f.tdet_writes==(channel==11?2:0));
    }
    for(unsigned kind=0;kind<5;kind++) {
        struct fake f={.tdet=6};struct mt6762_bif_transport t=transport(&f);
        struct mt6762_bif_pair p={123,456};
        if(kind==0)t.expected_tdet=4;
        if(kind==1)f.drop_clear=1;
        if(kind==2)f.drop_restore=1;
        if(kind==3){f.fault_channel=11;f.unexpected=1;}
        if(kind==4){f.fault_channel=11;f.unexpected=2;}
        assert(mt6762_bif_capture(&t,&p));failure_stays(&f,&t,&p);
        if(kind==0)assert(f.requests==0 && f.tdet_writes==0);
        if(kind==1)assert(f.tdet==6 && !t.restoration_unknown);
        if(kind==2)assert(f.tdet==4 && t.restoration_unknown);
        if(kind==3)assert(t.restoration_unknown && f.tdet_writes==1);
        if(kind==4)assert(!t.restoration_unknown && f.tdet==6 && f.tdet_writes==1);
    }
    for(unsigned channel=1;channel<=11;channel+=channel==1?2:8) {
        struct fake f={0};struct mt6762_bif_transport t=transport(&f);
        uint16_t raw=123;
        assert(!mt6762_battery_adc_fresh(&t.io,channel,&raw));
        assert(raw==(channel==1?26700:channel==3?1400:4089));
        if(channel!=1) {
            f.raw[channel==3?1:2]=0x1000;raw=123;
            assert(mt6762_battery_adc_fresh(&t.io,channel,&raw)==-4);
            assert(raw==123);
        }
        unsigned before=f.operations;
        assert(mt6762_battery_adc_fresh(&t.io,99,&raw)==-1);
        assert(f.operations==before);
    }
    for(unsigned channel=3;channel<=11;channel+=8) {
        struct fake f={.tdet=4,.fault_channel=channel,.stale=1};
        struct mt6762_bif_transport t=transport(&f);struct mt6762_bif_pair p={123,456};
        assert(mt6762_bif_capture(&t,&p)==-5 && t.fault);
        assert(mt6762_bif_retry_generation(&t,-5,1)==1 && !t.fault);
        assert(p.ntc_raw==123 && p.bif_raw==456 && !f.tdet_writes);
        f.stale=0;
        assert(!mt6762_bif_capture(&t,&p) && p.ntc_raw==1400 && p.bif_raw==4089);
    }
    for(unsigned kind=0;kind<7;kind++) {
        struct fake f={.tdet=4,.fault_channel=3,.stale=1};
        struct mt6762_bif_transport t=transport(&f);struct mt6762_bif_pair p={123,456};
        assert(mt6762_bif_capture(&t,&p)==-5);
        int error=-5;unsigned config=1;
        if(kind==0)error=-3; /* ADC timeout never recovers. */
        if(kind==1)config=0;
        if(kind==2)t.expected_tdet=6;
        if(kind==3)t.restoration_unknown=1;
        if(kind==4)f.tdet=6; /* Owned bit changed after measurement failure. */
        if(kind==5)f.fail_at=f.operations+1;
        if(kind==6)error=-2;
        assert(mt6762_bif_retry_generation(&t,error,config)!=1 && t.fault);
        failure_stays(&f,&t,&p);assert(!f.tdet_writes);
    }
    puts("PASS: fresh NTC/BIF generations, exact TDET restoration, persistent I/O failures, ownership loss and sticky rejection");
}
