/* Exact stock MT6765 SSPM mailbox-0 PLATFORM/CPU pin layout. No resets. */
#ifndef MT6762_SSPM_PROTOCOL_H
#define MT6762_SSPM_PROTOCOL_H
#include <stdint.h>
enum { MT6762_SSPM_DATA=0, MT6762_SSPM_CTRL=1 };
enum { MT6762_SSPM_INVALID=-1, MT6762_SSPM_BUSY=-2,
       MT6762_SSPM_IO=-3, MT6762_SSPM_TIMEOUT=-4, MT6762_SSPM_FAULT=-5 };
struct mt6762_sspm_io {
    void *context;
    int (*read)(void *,unsigned,uint32_t,uint32_t *);
    int (*write)(void *,unsigned,uint32_t,uint32_t);
    void (*barrier)(void *);
    void (*delay_us)(void *,unsigned);
};
struct mt6762_sspm_transport {
    struct mt6762_sspm_io io;
    unsigned owned_pins,fault;
};
/* Caller serializes all transactions and owns the selected AP pin, data
 * slots, and acknowledgement consumption. max_polls is a hard bound, each
 * failed poll delays 10 us. Errors never publish an acknowledgement. */
static inline int
mt6762_sspm_exchange(struct mt6762_sspm_transport *t,unsigned pin,
                    const uint32_t *words,unsigned count,uint32_t *ack,
                    unsigned max_polls)
{
    uint32_t in,out,value,bit;
    unsigned slot;
    const struct mt6762_sspm_io *io;
    if(!t || !words || !ack || pin>1 || !max_polls || max_polls>200000 ||
       count!=(pin?4u:3u) || !(t->owned_pins&(1u<<pin)))return MT6762_SSPM_INVALID;
    io=&t->io;
    if(!io->read || !io->write || !io->barrier || !io->delay_us)return MT6762_SSPM_INVALID;
    if(t->fault)return MT6762_SSPM_FAULT;
    bit=1u<<pin;slot=pin?3:0;
    if(io->read(io->context,MT6762_SSPM_CTRL,0,&in) ||
       io->read(io->context,MT6762_SSPM_CTRL,4,&out))goto io_error;
    /* Pending traffic belongs to a previous/other owner. Do not erase it. */
    if((in|out)&bit) {t->fault=1;return MT6762_SSPM_BUSY;}
    for(unsigned i=0;i<count;i++)
        if(io->write(io->context,MT6762_SSPM_DATA,(slot+i)*4,words[i]))goto io_error;
    io->barrier(io->context);
    if(io->write(io->context,MT6762_SSPM_CTRL,0,bit))goto io_error;
    io->barrier(io->context);
    for(unsigned i=0;i<max_polls;i++) {
        if(io->read(io->context,MT6762_SSPM_CTRL,4,&out))goto io_error;
        if(out&bit) {
            /* Capture response before freeing its acknowledgement. Clear only
             * our W1C bit, preserving unrelated mailbox channels. */
            io->barrier(io->context);
            if(io->read(io->context,MT6762_SSPM_DATA,slot*4,&value))goto io_error;
            /* A reply alone must not hide an unconsumed input doorbell. */
            if(io->read(io->context,MT6762_SSPM_CTRL,0,&in) || (in&bit))goto io_error;
            if(io->write(io->context,MT6762_SSPM_CTRL,4,bit))goto io_error;
            io->barrier(io->context);
            if(io->read(io->context,MT6762_SSPM_CTRL,4,&out))goto io_error;
            if(out&bit)goto io_error;
            *ack=value;return 0;
        }
        io->delay_us(io->context,10);
    }
    t->fault=1;return MT6762_SSPM_TIMEOUT;
io_error:
    t->fault=1;return MT6762_SSPM_IO;
}
#endif
