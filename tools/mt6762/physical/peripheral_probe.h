/* SPDX-License-Identifier: MIT -- passive, width-specific native entry record. */
#ifndef MT6762_PERIPHERAL_PROBE_H
#define MT6762_PERIPHERAL_PROBE_H
#include <stdint.h>
#include <stddef.h>
struct peripheral_entry {
    uint32_t address; uint8_t width,group; uint16_t valid;
    uint32_t value[2];
};
struct peripheral_record {
    uint8_t magic[8]; uint32_t version,size; uint8_t identity[32];
    uint32_t state,state_inverse,pass,index;
    uint64_t began[2],ended[2];
    struct peripheral_entry entries[250];
};
_Static_assert(sizeof(struct peripheral_record)==4096,"peripheral trace size");
_Static_assert(offsetof(struct peripheral_record,entries)==96,"peripheral entries offset");
struct peripheral_io {
    void *context;
    uint32_t (*read)(void *,uint32_t,unsigned);
    void (*barrier)(void *);
    uint64_t (*ticks)(void *);
};
extern volatile struct peripheral_record physical_peripherals;

static inline int peripheral_value(volatile struct peripheral_record *r,unsigned pass,
    uint32_t address,uint32_t *value)
{
    for(unsigned n=0;n<250;n++) {
        volatile struct peripheral_entry *e=&r->entries[n];
        if(e->address==address && (e->valid&(1u<<pass))) {*value=e->value[pass];return 1;}
    }
    return 0;
}
static inline int peripheral_group_ready(volatile struct peripheral_record *r,unsigned pass,unsigned group)
{
    uint32_t top,infra,con0,con1,power,other;
#define V(a,v) peripheral_value(r,pass,(a),&(v))
    /* Group5 is a bounded snapshot of ordinary LK text/static RAM. It has no
     * peripheral clock prerequisite and never follows a captured pointer. */
    if(!group || group==5)return 1;
    if(group==1)return V(0x10001090,infra) && !(infra&2);
    if(group==2 || group==3) {
        if(!V(0x100000a0,top) || !V(0x10001090,infra) ||
           (top&0x80) || (infra&(1u<<11)) || (top&7)>4)return 0;
        unsigned parent=top&7;
        if(parent) {
            uint32_t a=parent<=2?0x1000c26c:0x1000c23c;
            if(!V(a,con0) || !V(a+4,con1) || !V(a+12,power) ||
               !(con0&1) || !(con0&(1u<<23)) || !(con1&0x3fffff) || (power&3)!=1)return 0;
        }
        return group==2 || (V(0x10001094,infra) && !(infra&(1u<<18)));
    }
    if(group==4) {
        if(!V(0x10000070,top) || (top&0x8783)!=0x101 ||
           !V(0x10001094,infra) || (infra&4) || !V(0x100010c8,other) || (other&(1u<<9)))return 0;
        for(unsigned n=0;n<2;n++) {
            uint32_t a=n?0x1000c23c:0x1000c27c;
            if(!V(a,con0) || !V(a+4,con1) || !V(a+12,power) ||
               !(con0&1) || (n && !(con0&(1u<<23))) || !(con1&0x3fffff) || (power&3)!=1)return 0;
        }
        return 1;
    }
    return 0;
#undef V
}
static inline void peripheral_commit(const struct peripheral_io *io,
    volatile struct peripheral_record *r,uint32_t state)
{
    r->state_inverse=~state;io->barrier(io->context);
    r->state=state;io->barrier(io->context);
}
static inline void peripheral_capture(const struct peripheral_io *io,
    volatile struct peripheral_record *r)
{
    peripheral_commit(io,r,1);
    for(unsigned pass=0;pass<2;pass++) {
        r->pass=pass+1;r->began[pass]=io->ticks(io->context);
        for(unsigned n=0;n<250;n++) {
            volatile struct peripheral_entry *e=&r->entries[n];
            if(!e->address)break;
            r->index=n;io->barrier(io->context);
            if(!peripheral_group_ready(r,pass,e->group))continue;
            e->value[pass]=io->read(io->context,e->address,e->width);
            io->barrier(io->context);e->valid|=1u<<pass;
        }
        r->ended[pass]=io->ticks(io->context);
    }
    peripheral_commit(io,r,2);
}
#endif
