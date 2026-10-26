/* SPDX-License-Identifier: MIT -- read-only hardware; writes only owned RAM. */
#include "probe.h"
extern unsigned char image_start[],image_end[],physical_vectors[];
const uint32_t sspm_probe_addresses[SSPM_PROBE_WORDS]={
    0x00110c00,0x00110c04,0x00110c08,0x00110c0c,0x00110ea0,
    0x10450000,0x10450004,0x10450008,0x1045000c,0x10450010,0x10450014,0x10450018,
    0x10451004
};
const uint32_t sspm_probe_external_addresses[SSPM_PROBE_EXTERNAL_WORDS]={
    0x10000040,0x10000090,0x100010c8,0x1000c23c,0x1000c240,0x1000c248,
    0x10006350,0x10006358,0x1001a010,0x1001a024,0x1001a050,0x1001a054,0x1001a058
};
static const uint32_t screen_mask[8]={0x83,0x83,1u<<17,UINT32_MAX,UINT32_MAX,
    UINT32_MAX,UINT32_MAX,0x10013};
static const uint32_t screen_value[8]={1,1,0,0xd4800181,0x81150000,0x80000001,
    0xffff0000,0x12};
static void barrier(void) { __asm__ volatile("dsb sy" ::: "memory"); }
static uint64_t ticks(void)
{uint64_t value;__asm__ volatile("isb; mrs %0, cntpct_el0":"=r"(value)::"memory");return value;}
static int owned(const volatile void *p,size_t size,size_t alignment)
{
    uintptr_t a=(uintptr_t)p,lo=(uintptr_t)image_start,hi=(uintptr_t)image_end;
    return !(a&(alignment-1)) && a>=lo && a<=hi && size<=hi-a;
}
static void commit(volatile struct sspm_probe_record *r,uint32_t state)
{
    r->state_inverse=0;r->sequence_inverse=0;barrier();
    r->state=state;r->sequence++;
    barrier();r->sequence_inverse=~r->sequence;r->state_inverse=~state;barrier();
}
static int entry(volatile struct sspm_probe_record *r)
{
    uint64_t el,sp,mpidr,sctlr,vbar,daif,hz,guard;
    __asm__ volatile("mrs %0, CurrentEL":"=r"(el));
    if(el!=4)return 0;
    __asm__ volatile("mrs %0, SPSel":"=r"(sp));
    __asm__ volatile("mrs %0, mpidr_el1":"=r"(mpidr));
    __asm__ volatile("mrs %0, sctlr_el1":"=r"(sctlr));
    __asm__ volatile("mrs %0, vbar_el1":"=r"(vbar));
    __asm__ volatile("mrs %0, daif":"=r"(daif));
    __asm__ volatile("mrs %0, cntfrq_el0":"=r"(hz));
    __asm__ volatile("mov %0, x28":"=r"(guard));
    r->entry_mpidr=mpidr;r->entry_sctlr=sctlr;r->entry_vbar=vbar;r->entry_daif=daif;
    r->counter_hz=hz;
    return sp==1 && !(mpidr&UINT64_C(0xff00ffffff)) &&
        !(sctlr&((1u<<25)|5u)) && vbar==(uintptr_t)physical_vectors &&
        (daif&0x3c0)==0x3c0 && hz==SSPM_PROBE_COUNTER_HZ && !guard;
}
static int budget(volatile struct sspm_probe_record *r)
{
    uint64_t previous=r->ended_ticks,now=ticks();r->ended_ticks=now;
    if(now<previous || now<r->began_ticks){r->reason=SSPM_PROBE_TIME_REVERSED;return 0;}
    if(now-r->began_ticks>=r->budget_ticks){r->reason=SSPM_PROBE_DEADLINE;return 0;}
    return 1;
}
static int screen(volatile struct sspm_probe_record *r)
{
    r->operation=SSPM_PROBE_SCREEN;r->external_valid=0;r->screen_count++;
    commit(r,SSPM_PROBE_RUNNING);
    for(unsigned i=0;i<SSPM_PROBE_EXTERNAL_WORDS;i++) {
        uint32_t value=*(volatile uint32_t *)(uintptr_t)sspm_probe_external_addresses[i];
        barrier();r->external[i]=value;r->external_valid|=1u<<i;
        if(i<8 && (value&screen_mask[i])!=screen_value[i]) {
            r->bad_screen_word=i;r->reason=SSPM_PROBE_BAD_PROFILE;return 0;
        }
    }
    /* SECURITY_AO readings are recorded, never treated as permissions. */
    return 1;
}
int sspm_probe_run(volatile struct sspm_probe_record *r,const uint8_t identity[32])
{
    if(!owned(r,sizeof(*r),64) || !owned(identity,32,1))return SSPM_PROBE_REFUSED;
    uintptr_t id=(uintptr_t)identity,record=(uintptr_t)r;
    if(id<record+sizeof(*r) && id+32>record)return SSPM_PROBE_REFUSED;
    for(size_t i=0;i<sizeof(*r);i++)((volatile uint8_t *)r)[i]=0;
    const uint8_t magic[8]={'M','T','K','S','S','P','R','1'};
    for(unsigned i=0;i<8;i++)r->magic[i]=magic[i];
    for(unsigned i=0;i<32;i++)r->identity[i]=identity[i];
    r->version=1;r->size=sizeof(*r);r->index=UINT32_MAX;r->pass=UINT32_MAX;
    r->bad_screen_word=UINT32_MAX;r->budget_ticks=SSPM_PROBE_BUDGET_TICKS;
    for(unsigned i=0;i<SSPM_PROBE_WORDS;i++)r->words[i].address=sspm_probe_addresses[i];
    if(!entry(r)) {r->reason=SSPM_PROBE_BAD_ENTRY;commit(r,SSPM_PROBE_REFUSED);return SSPM_PROBE_REFUSED;}
    r->began_ticks=ticks();r->ended_ticks=r->began_ticks;
    commit(r,SSPM_PROBE_RUNNING);
    for(unsigned pass=0;pass<2;pass++)for(unsigned i=0;i<SSPM_PROBE_WORDS;i++) {
        r->pass=pass;r->index=i;
        if(!budget(r))goto expired;
        if(i==0 || i==5 || i==12) {
            if(!screen(r)){commit(r,SSPM_PROBE_REFUSED);return SSPM_PROBE_REFUSED;}
            if(!budget(r))goto expired;
        }
        uint32_t value=0;
        r->operation=SSPM_PROBE_LOAD;r->words[i].began_ticks[pass]=ticks();
        commit(r,SSPM_PROBE_RUNNING);
        int result=sspm_guard_read(i,&value,&r->fault);
        r->words[i].ended_ticks[pass]=ticks();r->ended_ticks=r->words[i].ended_ticks[pass];
        if(result==SSPM_GUARD_ABORT){commit(r,SSPM_PROBE_ABORT);return SSPM_PROBE_ABORT;}
        if(result!=SSPM_GUARD_OK){r->reason=SSPM_PROBE_GUARD_REJECTED;
            commit(r,SSPM_PROBE_REFUSED);return SSPM_PROBE_REFUSED;}
        r->words[i].value[pass]=value;r->words[i].valid|=1u<<pass;r->completed++;
        if(r->ended_ticks<r->words[i].began_ticks[pass]) {
            r->reason=SSPM_PROBE_TIME_REVERSED;goto expired;
        }
        commit(r,SSPM_PROBE_RUNNING);
    }
    r->operation=SSPM_PROBE_IDLE;commit(r,SSPM_PROBE_COMPLETE);return SSPM_PROBE_COMPLETE;
expired:
    commit(r,SSPM_PROBE_EXPIRED);return SSPM_PROBE_EXPIRED;
}
