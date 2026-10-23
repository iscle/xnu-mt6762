#include "power_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct fake_i2c { uint8_t regs[7]; int calls,fail_call,short_call,writes; };
static int transfer(void *arg,struct power_i2c_msg *m,size_t n)
{
    struct fake_i2c *f=arg;
    f->calls++;
    if(f->calls==f->fail_call) return -5;
    if(f->calls==f->short_call) return (int)n-1;
    assert(m[0].address==0x6a && !m[0].read);
    if(n==2){
        assert(m[0].length==1 && m[1].address==0x6a && m[1].read && m[1].length==1);
        m[1].data[0]=f->regs[m[0].data[0]];
    }else{
        assert(n==1 && m[0].length==2 && m[0].data[0]==1);
        f->regs[1]=m[0].data[1]; f->writes++;
    }
    return (int)n;
}
struct fake_mmio { uint32_t status[8]; unsigned n,i,writes; int fail; };
static int rd(void *arg,uint32_t off,uint32_t *v)
{
    struct fake_mmio *f=arg; assert(off==0xc24);
    if(f->fail)return -1;
    *v=f->status[f->i<f->n?f->i++:f->n-1]; return 0;
}
static int wr(void *arg,uint32_t off,uint32_t v)
{
    struct fake_mmio *f=arg;
    if(!f->writes) {assert(off==0xc20); assert(v==0x00120000);}
    else {assert(off==0xc28);assert(v==1);}
    f->writes++;return 0;
}
int main(void)
{
    /* Actual boot trace: ID f0, Reg1 f8 -> fc on disable, preserved fields. */
    struct fake_i2c f={{0,0xf8,0x90,0xf0,0x76,0x24,0},0,0,0,0};
    struct power_i2c b={&f,transfer};
    struct psc5425e_snapshot s;
    assert(!psc5425e_snapshot(&b,&s));
    assert(s.identity==0xf0 && !s.done && !s.charge_disabled && s.current==0x76);
    assert(!psc5425e_disable_charge(&b) && f.regs[1]==0xfc && f.writes==1);
    assert(!psc5425e_disable_charge(&b) && f.writes==1);
    f.regs[0]=0x20;assert(!psc5425e_snapshot(&b,&s)&&s.done);
    f.regs[0]=0x30;assert(!psc5425e_snapshot(&b,&s)&&!s.done);
    /* Read failure must not become valid status or cause a register write. */
    memset(&s,0x55,sizeof(s));f.fail_call=f.calls+3;
    assert(psc5425e_snapshot(&b,&s)==POWER_IO && s.identity==0x55);
    f.fail_call=f.calls+2;
    assert(psc5425e_disable_charge(&b)==POWER_IO && f.writes==1);
    uint8_t value=0x77;f.short_call=f.calls+1;
    assert(psc5425e_read(&b,0,&value)==POWER_IO && value==0x77);
    f.regs[3]=0;assert(psc5425e_disable_charge(&b)==POWER_ID_MISMATCH && f.writes==1);
    struct fake_mmio mm={{0x200000,0x220000,0x26000e},3,0,0,0};
    struct power_mmio m={&mm,rd,wr};uint16_t v=0xbeef;
    assert(!mt6765_pwrap_read16(&m,0x24,&v,4)&&v==14&&mm.writes==2);
    mm=(struct fake_mmio){{0x220000},1,0,0,0};
    assert(mt6765_pwrap_read16(&m,0x24,&v,3)==POWER_TIMEOUT&&mm.writes==0&&mm.i==1);
    mm=(struct fake_mmio){{0},1,0,0,0};
    assert(mt6765_pwrap_read16(&m,0x24,&v,3)==POWER_NOT_READY&&mm.writes==0);
    assert(mt6765_pwrap_read16(&m,0x25,&v,3)==POWER_INVALID);
    struct mt6357_keys k=mt6357_decode_topstatus(14);assert(!k.power&&!k.home&&k.charger_present);
    k=mt6357_decode_topstatus(0);assert(k.power&&k.home&&!k.charger_present);
    uint16_t keys[5]={0xffff,0xffff,0xffff,0xffff,0xffff};
    assert(mt6765_key_pressed(keys,0)==0);keys[0]=0xfffe;
    assert(mt6765_key_pressed(keys,0)==1&&mt6765_key_pressed(keys,1)==0);
    assert(mt6765_key_pressed(keys,72)==POWER_INVALID);
    puts("PASS: recovered I2C transactions, disable trace, errors, WACS2, and key decoding");
}
