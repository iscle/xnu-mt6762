/* SPDX-License-Identifier: MIT */
#include "conn_power.h"
#include <stddef.h>

#define RGU UINT32_C(0x10007018)
#define SPM UINT32_C(0x1000632c)
#define ACK0 UINT32_C(0x10006180)
#define ACK1 UINT32_C(0x10006184)
#define PROT_EN UINT32_C(0x10001220)
#define PROT_ACK UINT32_C(0x10001228)
#define PROT1_EN UINT32_C(0x10001250)
#define PROT1_ACK UINT32_C(0x10001258)
#define PROT_CLR UINT32_C(0x100012a4)
#define PROT1_CLR UINT32_C(0x100012ac)
#define CHIP_ID UINT32_C(0x180b1010)
#define EXPECTED_ID UINT32_C(0x10020300)
#define RESET UINT32_C(0x1000)
#define RESET_KEY UINT32_C(0x88000000)
#define PROT_MASK UINT32_C(0x16000)
#define PROT1_MASK UINT32_C(0x40000)

struct run {
    const struct mt6762_conn_io *io;
    struct mt6762_conn_report *r;
    uint64_t stage_start, stage_budget;
    uint32_t stage_iterations;
};
static int fail(struct run *s, int error)
{
    s->r->result=error;
    return error;
}
static int deadline(struct run *s)
{
    uint64_t now=s->io->ticks(s->io->context);
    s->r->ended_ticks=now;
    if(now-s->r->began_ticks >= (uint64_t)s->io->total_timeout_us*13 ||
       now-s->stage_start >= s->stage_budget)
        return fail(s,MT6762_CONN_TIMEOUT);
    return 0;
}
static void stage(struct run *s, enum mt6762_conn_stage value, uint32_t us)
{
    s->r->stage=value;
    s->stage_start=s->io->ticks(s->io->context);
    s->stage_budget=(uint64_t)us*13;
    s->stage_iterations=0;
}
static int iteration(struct run *s)
{
    if(deadline(s))return s->r->result;
    if(s->stage_iterations++ >= s->io->iteration_limit)
        return fail(s,MT6762_CONN_ITERATION_LIMIT);
    s->r->iterations++;
    return 0;
}
static int admission(struct run *s)
{
    if(deadline(s))return s->r->result;
    s->r->prerequisite_checks++;
    int error=s->io->prerequisites(s->io->context,s->r->stage);
    if(error) {
        s->r->callback_error=error;
        return fail(s,MT6762_CONN_PREREQUISITE);
    }
    return deadline(s);
}
static int read_word(struct run *s, uint32_t address, uint32_t *value)
{
    if(admission(s))return s->r->result;
    s->r->last_address=address;
    s->r->last_value_valid=0;s->r->last_access_write=0;
    uint32_t raw=0;
    int error=s->io->read32(s->io->context,address,&raw);
    s->r->reads++;
    if(error) {
        s->r->callback_error=error;
        return fail(s,MT6762_CONN_IO);
    }
    *value=raw;
    s->r->last_value=raw;s->r->last_value_valid=1;
    if(address==RGU)s->r->reset_observed=!!(raw&RESET);
    if(address==CHIP_ID) {s->r->id=raw;s->r->id_valid=1;}
    return deadline(s);
}
static int write_word(struct run *s, uint32_t address, uint32_t value)
{
    if(admission(s))return s->r->result;
    s->r->last_address=address;s->r->last_value=value;
    s->r->last_value_valid=1;s->r->last_access_write=1;
    s->r->write_attempts++;
    if(address==RGU)s->r->reset_write_attempted=1;
    if(address==SPM)s->r->power_write_attempted=1;
    s->io->barrier(s->io->context);
    int error=s->io->write32(s->io->context,address,value);
    s->io->barrier(s->io->context);
    if(error) {
        s->r->callback_error=error;
        return fail(s,MT6762_CONN_IO);
    }
    s->r->writes++;
    return deadline(s);
}
static int require_field(struct run *s, uint32_t address, uint32_t mask,
    uint32_t expected, int mismatch)
{
    uint32_t value;
    if(read_word(s,address,&value))return s->r->result;
    if((value&mask)!=expected)return fail(s,mismatch);
    return 0;
}
static int snapshot(struct run *s, int cold)
{
    static const uint32_t addr[8]={RGU,SPM,ACK0,ACK1,PROT_EN,PROT_ACK,PROT1_EN,PROT1_ACK};
    static const uint32_t mask[8]={RESET,0x1f,2,2,PROT_MASK,PROT_MASK,PROT1_MASK,PROT1_MASK};
    const uint32_t expected_cold[8]={0,0x12,0,0,PROT_MASK,PROT_MASK,PROT1_MASK,PROT1_MASK};
    const uint32_t expected_ready[8]={RESET,0x0d,2,2,0,0,0,0};
    for(unsigned i=0;i<8;i++) {
        uint32_t value;
        if(read_word(s,addr[i],&value))return s->r->result;
        s->r->snapshot[i]=value;s->r->snapshot_valid|=1u<<i;
        /* RGU can already be asserted while cold. Accept only a clear key
         * readback or the exact shipped key, never invent another key. */
        if(cold && i==0) {
            uint32_t key=value&UINT32_C(0xff000000);
            if(key && key!=RESET_KEY)return fail(s,MT6762_CONN_NOT_COLD);
        } else if((value&mask[i])!=(cold?expected_cold[i]:expected_ready[i]))
            return fail(s,cold?MT6762_CONN_NOT_COLD:MT6762_CONN_STATE_CHANGED);
    }
    return 0;
}
static int spm_transition(struct run *s, enum mt6762_conn_stage next,
    uint32_t before, uint32_t after)
{
    stage(s,next,s->io->transition_timeout_us);
    if(require_field(s,RGU,RESET,RESET,MT6762_CONN_STATE_CHANGED))return s->r->result;
    if(next>=MT6762_CONN_ENABLE_CLOCK &&
       (require_field(s,ACK0,2,2,MT6762_CONN_STATE_CHANGED) ||
        require_field(s,ACK1,2,2,MT6762_CONN_STATE_CHANGED)))return s->r->result;
    uint32_t value;
    if(read_word(s,SPM,&value))return s->r->result;
    if((value&0x1f)!=before)return fail(s,MT6762_CONN_STATE_CHANGED);
    if(write_word(s,SPM,(value&~UINT32_C(0x1f))|after))return s->r->result;
    return require_field(s,SPM,0x1f,after,MT6762_CONN_STATE_CHANGED);
}
static int wait_power(struct run *s)
{
    stage(s,MT6762_CONN_POWER_ACK,s->io->transition_timeout_us);
    for(;;) {
        uint32_t first,second;
        if(iteration(s) || read_word(s,ACK0,&first) || read_word(s,ACK1,&second))return s->r->result;
        if((first&2) && (second&2))return 0;
        s->io->relax(s->io->context);
    }
}
static int release_protection(struct run *s, enum mt6762_conn_stage next,
    uint32_t address, uint32_t clear, uint32_t enable, uint32_t ack,
    uint32_t mask, uint32_t before, uint32_t after)
{
    stage(s,next,s->io->transition_timeout_us);
    if(require_field(s,RGU,RESET,RESET,MT6762_CONN_STATE_CHANGED) ||
       require_field(s,SPM,0x1f,0x0d,MT6762_CONN_STATE_CHANGED) ||
       require_field(s,ACK0,2,2,MT6762_CONN_STATE_CHANGED) ||
       require_field(s,ACK1,2,2,MT6762_CONN_STATE_CHANGED) ||
       require_field(s,enable,mask,before,MT6762_CONN_STATE_CHANGED) ||
       require_field(s,ack,mask,before,MT6762_CONN_STATE_CHANGED) ||
       write_word(s,address,clear))return s->r->result;
    /* These bounded ordinary readbacks are stricter than stock's release
     * function, which issues three CLR writes without waiting for ACK. */
    for(;;) {
        uint32_t en,sta;
        if(iteration(s) || read_word(s,enable,&en) || read_word(s,ack,&sta))return s->r->result;
        if((en&mask)==after && (sta&mask)==after)return 0;
        s->io->relax(s->io->context);
    }
}
static int wait_us(struct run *s, uint32_t us)
{
    uint64_t start=s->io->ticks(s->io->context);
    for(;;) {
        if(iteration(s))return s->r->result;
        if(s->io->ticks(s->io->context)-start >= (uint64_t)us*13)return 0;
        s->io->relax(s->io->context);
    }
}
int mt6762_conn_power_reset_held(const struct mt6762_conn_io *io,
    struct mt6762_conn_report *r, int enabled)
{
    if(!r)return MT6762_CONN_ARGUMENT;
    /* Freestanding-friendly explicit initialization, no runtime memset. */
    volatile unsigned char *bytes=(volatile unsigned char *)r;
    for(unsigned i=0;i<sizeof(*r);i++)bytes[i]=0;
    if(!enabled) {r->result=MT6762_CONN_DISABLED;return r->result;}
    if(enabled!=1 || !io || !io->read32 || !io->write32 || !io->ticks ||
       !io->barrier || !io->relax || !io->prerequisites || io->counter_hz!=13000000 ||
       !io->transition_timeout_us || io->transition_timeout_us>100000 ||
       !io->total_timeout_us || io->total_timeout_us>1000000 ||
       !io->iteration_limit || io->iteration_limit>10000000) {
        r->result=MT6762_CONN_ARGUMENT;return r->result;
    }
    struct run s={io,r,0,0,0};
    r->began_ticks=io->ticks(io->context);
    stage(&s,MT6762_CONN_COLD_ENTRY,io->transition_timeout_us);
    /* Two masked cold observations before ANY writes. They are sequential,
     * not atomic; the caller's exclusive ownership is essential. */
    if(snapshot(&s,1) || snapshot(&s,1))return r->result;
    stage(&s,MT6762_CONN_ASSERT_RESET,io->transition_timeout_us);
    uint32_t reset;
    if(read_word(&s,RGU,&reset) || write_word(&s,RGU,reset|RESET_KEY|RESET) ||
       require_field(&s,RGU,RESET,RESET,MT6762_CONN_STATE_CHANGED))return r->result;
    if(spm_transition(&s,MT6762_CONN_POWER_ON,0x12,0x16) ||
       spm_transition(&s,MT6762_CONN_POWER_ON_SECONDARY,0x16,0x1e) ||
       wait_power(&s) ||
       spm_transition(&s,MT6762_CONN_ENABLE_CLOCK,0x1e,0x0e) ||
       spm_transition(&s,MT6762_CONN_REMOVE_ISOLATION,0x0e,0x0c) ||
       spm_transition(&s,MT6762_CONN_DOMAIN_RESET_B,0x0c,0x0d) ||
       release_protection(&s,MT6762_CONN_RELEASE_PROTECT_14_16,PROT_CLR,0x14000,
           PROT_EN,PROT_ACK,PROT_MASK,0x16000,0x2000) ||
       release_protection(&s,MT6762_CONN_RELEASE_PROTECT_13,PROT_CLR,0x2000,
           PROT_EN,PROT_ACK,PROT_MASK,0x2000,0) ||
       release_protection(&s,MT6762_CONN_RELEASE_PROTECT1_18,PROT1_CLR,0x40000,
           PROT1_EN,PROT1_ACK,PROT1_MASK,0x40000,0))return r->result;
    stage(&s,MT6762_CONN_SETTLE,io->transition_timeout_us);
    if(wait_us(&s,10))return r->result;
    stage(&s,MT6762_CONN_READ_ID,200000);
    /* Stock probes at 20 ms intervals. Isolate the ordinary ID load here;
     * the rest of polling_consys_chipid performs patch/configuration writes. */
    for(unsigned attempt=0;attempt<10;attempt++) {
        uint32_t id;
        if(iteration(&s) || snapshot(&s,0) || read_word(&s,CHIP_ID,&id))return r->result;
        if(id==EXPECTED_ID) {
            if(admission(&s))return r->result;
            r->stage=MT6762_CONN_RESET_HELD_ID_VERIFIED;
            r->result=MT6762_CONN_OK;return 0;
        }
        if(attempt!=9 && wait_us(&s,20000))return r->result;
    }
    return fail(&s,MT6762_CONN_ID_MISMATCH);
}
