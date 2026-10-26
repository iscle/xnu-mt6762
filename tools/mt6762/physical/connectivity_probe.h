/* SPDX-License-Identifier: MIT
 * Fixed, passive AP/MT6357 connectivity survey. No ownership or power-on grant.
 * Callbacks must be bounded and the PMIC callback serialized/read-only. This
 * header neither maps MMIO nor installs exception recovery nor allocates RAM.
 */
#ifndef MT6762_CONNECTIVITY_PROBE_H
#define MT6762_CONNECTIVITY_PROBE_H
#include <stdint.h>
#include <stddef.h>

#define MT6762_CONNECTIVITY_AP_COUNT 21u
#define MT6762_CONNECTIVITY_PMIC_COUNT 19u
#define MT6762_CONNECTIVITY_COUNT 40u
#define MT6762_CONNECTIVITY_NOT_READ INT32_MIN
#define MT6762_CONNECTIVITY_DEFAULT_BUDGET_US 250000u
#define MT6762_CONNECTIVITY_MAX_BUDGET_US 1000000u
enum { MT6762_CONNECTIVITY_AP=0, MT6762_CONNECTIVITY_PMIC=1 };
enum { MT6762_CONNECTIVITY_NOT_STARTED=0, MT6762_CONNECTIVITY_DISABLED=1, MT6762_CONNECTIVITY_READING=2,
       MT6762_CONNECTIVITY_COMPLETE=3, MT6762_CONNECTIVITY_FAILED=4 };
enum { MT6762_CONNECTIVITY_OK=0, MT6762_CONNECTIVITY_OFF=1,
       MT6762_CONNECTIVITY_ARGUMENT=-1, MT6762_CONNECTIVITY_TRANSPORT=-2,
       MT6762_CONNECTIVITY_DEADLINE=-3, MT6762_CONNECTIVITY_TIMER=-4,
       MT6762_CONNECTIVITY_PWRAP_GATED=-5, MT6762_CONNECTIVITY_PMIC_FAMILY=-6 };

/* Never follow an address from the writable record. This closed table is the
 * only source of survey requests; none are SET/CLR or CONN-domain words. */
static const uint32_t mt6762_connectivity_ap_regs[MT6762_CONNECTIVITY_AP_COUNT]={
    0x10006180,0x10006184,0x1000632c,0x10001220,0x10001228,
    0x10001250,0x10001258,0x10007018,0x10001380,0x10001388,
    0x100053e0,0x100053f0,0x10002c00,0x10002c10,0x10001090,
    0x10001094,0x1000d188,0x1000d18c,0x1000d190,0x1000d194,
    0x1000d198
};
static const uint16_t mt6762_connectivity_pmic_regs[MT6762_CONNECTIVITY_PMIC_COUNT]={
    0x0008,0x1a58,0x1a5a,0x1a60,0x1a66,0x1b1c,0x1b1e,0x1b24,
    0x1b2a,0x1b2c,0x1c1c,0x1b88,0x1b8a,0x1b90,0x1b96,
    0x0788,0x07b0,0x044a,0x07ac
};
struct mt6762_connectivity_entry {
    uint32_t address;
    uint8_t bus,width;
    uint16_t valid;
    uint32_t value[2];
    int32_t error[2];
};
struct mt6762_connectivity_record {
    uint8_t magic[8];
    uint32_t version,size;
    uint8_t identity[32];
    uint32_t state,state_inverse,pass,index;
    uint64_t began[2],ended[2];
    uint32_t counter_hz,budget_us;
    int32_t result,transport_error;
    struct mt6762_connectivity_entry entries[MT6762_CONNECTIVITY_COUNT];
    uint8_t reserved[3024];
};
_Static_assert(sizeof(struct mt6762_connectivity_entry)==24,"connectivity entry ABI");
_Static_assert(offsetof(struct mt6762_connectivity_record,entries)==112,"connectivity record ABI");
_Static_assert(sizeof(struct mt6762_connectivity_record)==4096,"connectivity record size");
struct mt6762_connectivity_io {
    void *context;
    int (*read_ap32)(void *,uint32_t,uint32_t *);
    int (*read_pmic16)(void *,uint16_t,uint16_t *);
    uint64_t (*ticks)(void *);
    void (*barrier)(void *);
    uint32_t counter_hz,budget_us;
};
static inline int mt6762_connectivity_pmic_allowed(uint16_t address)
{
    for(unsigned i=0;i<MT6762_CONNECTIVITY_PMIC_COUNT;i++)
        if(mt6762_connectivity_pmic_regs[i]==address)return 1;
    return 0;
}
static inline void mt6762_connectivity_commit(const struct mt6762_connectivity_io *io,
    volatile struct mt6762_connectivity_record *r,uint32_t state)
{
    r->state_inverse=~state;
    if(io)io->barrier(io->context);
    r->state=state;
    if(io)io->barrier(io->context);
}
/* enabled must be exactly1. Disabled calls initialize a DISABLED record and
 * invoke no callbacks, even if io is supplied. No production call site or
 * physical allocation is provided here. Parent integration must reserve and
 * retain this4096-byte record separately before calling this function.
 *
 * Two sequential passes,80 requests at most; stop on first error. A returned
 * callback failure never commits its value. Both pass times and unfinished
 * entries remain distinguishable. Deadlines are checked between callbacks;
 * they do not interrupt a hung MMIO load or callback. Fixed request count also
 * bounds this function when the timer stops advancing.
 */
static inline int mt6762_connectivity_capture(const struct mt6762_connectivity_io *io,
    volatile struct mt6762_connectivity_record *r,const uint8_t identity[32],int enabled)
{
    static const uint8_t magic[8]={'M','T','K','C','O','N','N','1'};
    if(!r)return MT6762_CONNECTIVITY_ARGUMENT;
    volatile uint8_t *bytes=(volatile uint8_t *)r;
    for(unsigned i=0;i<sizeof(*r);i++)bytes[i]=0;
    for(unsigned i=0;i<8;i++)r->magic[i]=magic[i];
    if(identity)for(unsigned i=0;i<32;i++)r->identity[i]=identity[i];
    r->version=1;r->size=sizeof(*r);r->index=UINT32_MAX;
    for(unsigned i=0;i<MT6762_CONNECTIVITY_COUNT;i++) {
        volatile struct mt6762_connectivity_entry *e=&r->entries[i];
        e->bus=i<MT6762_CONNECTIVITY_AP_COUNT?MT6762_CONNECTIVITY_AP:MT6762_CONNECTIVITY_PMIC;
        e->width=e->bus==MT6762_CONNECTIVITY_AP?4:2;
        e->address=e->bus==MT6762_CONNECTIVITY_AP?mt6762_connectivity_ap_regs[i]:
            mt6762_connectivity_pmic_regs[i-MT6762_CONNECTIVITY_AP_COUNT];
        e->error[0]=e->error[1]=MT6762_CONNECTIVITY_NOT_READ;
    }
    if(!enabled) {
        r->result=MT6762_CONNECTIVITY_OFF;
        mt6762_connectivity_commit(NULL,r,MT6762_CONNECTIVITY_DISABLED);
        return MT6762_CONNECTIVITY_OFF;
    }
    if(enabled!=1 || !identity || !io || !io->read_ap32 || !io->read_pmic16 ||
       !io->ticks || !io->barrier || !io->budget_us ||
       io->budget_us>MT6762_CONNECTIVITY_MAX_BUDGET_US) {
        r->result=MT6762_CONNECTIVITY_ARGUMENT;
        mt6762_connectivity_commit(NULL,r,MT6762_CONNECTIVITY_FAILED);
        return MT6762_CONNECTIVITY_ARGUMENT;
    }
    r->counter_hz=io->counter_hz;r->budget_us=io->budget_us;
    if(io->counter_hz!=13000000u) {
        r->result=MT6762_CONNECTIVITY_TIMER;
        mt6762_connectivity_commit(io,r,MT6762_CONNECTIVITY_FAILED);
        return MT6762_CONNECTIVITY_TIMER;
    }
    const uint64_t budget=(uint64_t)io->budget_us*13u;
    const uint64_t began=io->ticks(io->context);
    mt6762_connectivity_commit(io,r,MT6762_CONNECTIVITY_READING);
    for(unsigned pass=0;pass<2;pass++) {
        r->pass=pass+1;r->began[pass]=io->ticks(io->context);
        for(unsigned i=0;i<MT6762_CONNECTIVITY_COUNT;i++) {
            volatile struct mt6762_connectivity_entry *e=&r->entries[i];
            uint32_t value=0;uint16_t pmic=0;int error;
            r->index=i;io->barrier(io->context);
            if(io->ticks(io->context)-began>=budget) {
                e->error[pass]=MT6762_CONNECTIVITY_DEADLINE;
                r->result=MT6762_CONNECTIVITY_DEADLINE;goto failed;
            }
            /* INFRA+90 was read earlier in this same pass. Do not access
             * the PWRAP configuration window through a disabled clock. */
            if(i>=16 && i<MT6762_CONNECTIVITY_AP_COUNT &&
               (r->entries[14].value[pass]&2)) {
                e->error[pass]=MT6762_CONNECTIVITY_PWRAP_GATED;
                r->result=MT6762_CONNECTIVITY_PWRAP_GATED;goto failed;
            }
            if(i<MT6762_CONNECTIVITY_AP_COUNT)
                error=io->read_ap32(io->context,mt6762_connectivity_ap_regs[i],&value);
            else {
                error=io->read_pmic16(io->context,
                    mt6762_connectivity_pmic_regs[i-MT6762_CONNECTIVITY_AP_COUNT],&pmic);
                value=pmic;
            }
            e->error[pass]=error;
            if(error) {
                r->transport_error=error;r->result=MT6762_CONNECTIVITY_TRANSPORT;
                goto failed;
            }
            e->value[pass]=value;io->barrier(io->context);e->valid|=1u<<pass;
            /* HWCID is the FIRST PMIC read of each pass. Preserve the raw
             * successful observation even on family mismatch, but never
             * proceed to MT6357-specific words on another/unknown device. */
            if(i==MT6762_CONNECTIVITY_AP_COUNT && (value>>8)!=0x57) {
                r->result=MT6762_CONNECTIVITY_PMIC_FAMILY;goto failed;
            }
            /* A successful but slow final callback must not hide expiry. Its
             * returned value remains valid; the capture still ends FAILED. */
            if(io->ticks(io->context)-began>=budget) {
                r->result=MT6762_CONNECTIVITY_DEADLINE;goto failed;
            }
        }
        r->ended[pass]=io->ticks(io->context);
        if(r->ended[pass]-began>=budget) {
            r->result=MT6762_CONNECTIVITY_DEADLINE;goto failed;
        }
        continue;
failed:
        r->ended[pass]=io->ticks(io->context);
        mt6762_connectivity_commit(io,r,MT6762_CONNECTIVITY_FAILED);
        return r->result;
    }
    r->result=MT6762_CONNECTIVITY_OK;
    mt6762_connectivity_commit(io,r,MT6762_CONNECTIVITY_COMPLETE);
    return MT6762_CONNECTIVITY_OK;
}
#endif
