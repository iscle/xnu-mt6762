/* SPDX-License-Identifier: MIT */
#include "conn_rom.h"
#include "sha256.h"
static const struct cr_profile profiles[CR_IMAGES]={
    {"soc1_0_ram_bt_1_1_hdr.bin",0,571085,0x80000,0x68300,
     {0x15,0x92,0x5c,0x53,0x25,0x03,0x67,0x43,0x91,0xd7,0xa6,0x0b,0xf8,0x52,0xa5,0x47,0xcd,0x8c,0x6c,0x69,0x89,0x2b,0x8d,0x41,0x77,0x1e,0x23,0xed,0x0a,0x56,0x53,0x5c},
     {0xaf,0xfa,0x62,0x20,0x69,0xf4,0x4e,0xe3,0x81,0x00,0x81,0xee,0xd9,0x4a,0x56,0xea,0x9d,0x86,0x06,0x8c,0x15,0x44,0xc2,0x56,0xca,0x62,0xc5,0x10,0x85,0xab,0x87,0x4e}},
    {"soc1_0_ram_wifi_1_1_hdr.bin",3,196208,0x140000,0x68310,
     {0x04,0xdd,0x64,0x17,0xcc,0xec,0x83,0xfa,0x83,0xa2,0xcf,0x0d,0xe4,0x4b,0x68,0x61,0x78,0x46,0x50,0x24,0xdd,0x5d,0x84,0xdc,0x10,0x8e,0xbe,0x42,0x39,0xcf,0xac,0xd7},
     {0xed,0xd8,0x15,0xde,0x21,0xfe,0x4e,0x35,0xcf,0x2b,0x0b,0x04,0xf4,0x58,0x6c,0x79,0x29,0x45,0x31,0x2a,0x76,0xde,0x3d,0xcd,0x33,0xf4,0x18,0x53,0x2f,0xe0,0x38,0x18}},
    {"soc1_0_ram_mcu_1_1_hdr.bin",4,105940,0x0,0x68320,
     {0x75,0x5b,0x48,0x58,0xa2,0x2a,0x50,0x72,0xe3,0xfd,0x7b,0x50,0x6f,0x2d,0xe9,0x82,0xa7,0x45,0xf9,0xb1,0x07,0x54,0x98,0x04,0x29,0x22,0x7a,0x01,0xa7,0xff,0x3d,0x24},
     {0x82,0x89,0xe9,0x58,0xeb,0xf1,0x5f,0x3b,0x9c,0xe7,0xc6,0x09,0x53,0x26,0xa8,0xcf,0x36,0x58,0xab,0x01,0xac,0x76,0xab,0xfe,0xcd,0x18,0xbc,0xcd,0xd2,0xfa,0x01,0x37}},
};
const struct cr_profile *cr_profile_at(size_t i) { return i<CR_IMAGES?profiles+i:0; }
static void copy(void *d,const void *s,size_t n) { uint8_t *a=d;const uint8_t *b=s;size_t i;for(i=0;i<n;i++)a[i]=b[i]; }
static void zero(void *d,size_t n) { uint8_t *a=d;size_t i;for(i=0;i<n;i++)a[i]=0; }
static int equal(const uint8_t *a,const uint8_t *b,size_t n) { size_t i;unsigned v=0;for(i=0;i<n;i++)v|=a[i]^b[i];return v==0; }
static int overlap(uint64_t a,uint64_t n,uint64_t b,uint64_t m) { return a<b+m && b<a+n; }
static int pointer_range(const void *p,size_t n) { return p && n && (uintptr_t)p<=UINTPTR_MAX-n; }
static uint32_t le32(const uint8_t *b) { return (uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24; }
struct context { struct cr_workspace *w;struct cr_report *r;uint64_t budget;unsigned baseline; };
static int time_check(struct context *c)
{
    c->r->ended_ticks=c->w->io.ticks(c->w->io.context);
    return c->r->ended_ticks-c->r->began_ticks>=c->budget?CR_TIMEOUT:CR_OK;
}
static int guard(struct context *c,enum cr_phase phase)
{
    struct cr_live now;int e;struct cr_request *q=&c->w->request;
    struct cr_report *r=c->r;struct cr_io *io=&c->w->io;
    r->phase=phase;
    if(r->operations>=q->operation_limit)return CR_LIMIT;
    r->operations++;
    if((e=time_check(c)))return e;
    zero(&now,sizeof(now));
    e=io->observe(io->context,phase,&now);r->callback_error=e;
    if(e){(void)time_check(c);return CR_ADMISSION;}
    r->observations++;copy(&r->last,&now,sizeof(now));
    if((e=time_check(c)))return e;
    if(now.lease_epoch!=q->lease_epoch || now.owned_base!=q->consys_base ||
       now.owned_bytes!=q->consys_bytes || !(now.rgu_reset&0x1000) ||
       (now.spm_control&0x1f)!=0xd || !(now.power_status&2) ||
       !(now.power_status2&2) || now.ip_id!=0x10020300 ||
       (now.fw_version&255)!=0 || (now.emi_remap&0xfff)!=(q->consys_base>>24))return CR_STATE;
    if(c->baseline) {
        if(now.hw_version!=r->first.hw_version || now.fw_version!=r->first.fw_version)return CR_STATE;
    } else {copy(&r->first,&now,sizeof(now));c->baseline=1;}
    return CR_OK;
}
static int io_end(struct context *c,int callback)
{
    int e=time_check(c);c->r->callback_error=callback;
    return callback?CR_IO:e;
}
static int transfer(struct context *c,uint64_t pa,size_t n,enum cr_phase phase)
{
    int e,status;size_t done=0;struct cr_report *r=c->r;struct cr_io *io=&c->w->io;
    r->last_address=pa;r->last_requested=n;r->last_completed=0;
    if((e=guard(c,phase)))return e;
    r->write_attempts++;
    status=io->write(io->context,pa,c->w->source,n,&done);r->last_completed=done;
    if(!status && done==n){r->writes++;r->bytes_written+=n;}
    if((e=io_end(c,status)))return e;
    if(done!=n)return CR_SHORT;
    if((e=guard(c,CR_PUBLISH)))return e;
    status=io->synchronize(io->context,pa,n,CR_CACHE_PUBLISH);
    if(!status)r->synchronizations++;
    if((e=io_end(c,status)))return e;
    if((e=guard(c,CR_INVALIDATE)))return e;
    status=io->synchronize(io->context,pa,n,CR_CACHE_PREPARE_READ);
    if(!status)r->synchronizations++;
    if((e=io_end(c,status)))return e;
    if((e=guard(c,CR_READBACK_PHASE)))return e;
    done=0;
    status=io->read(io->context,pa,c->w->readback,n,&done);r->last_completed=done;
    if(!status && done==n)r->reads++;
    if((e=io_end(c,status)))return e;
    if(done!=n)return CR_SHORT;
    if(!equal(c->w->source,c->w->readback,n))return CR_READBACK;
    r->bytes_verified+=n;
    return CR_OK;
}
static int layout(const struct cr_request *q,const struct cr_io *io,
                  struct cr_workspace *w,struct cr_report *r)
{
    const void *ptr[7]={q,io,w,r,0,0,0};
    size_t len[7]={sizeof(*q),sizeof(*io),sizeof(*w),sizeof(*r),0,0,0};
    size_t i,j;
    for(i=0;i<4;i++)if(!pointer_range(ptr[i],len[i]))return CR_ARGUMENT;
    for(i=0;i<4;i++)for(j=0;j<i;j++)
        if(overlap((uintptr_t)ptr[i],len[i],(uintptr_t)ptr[j],len[j]))return CR_ARGUMENT;
    if(!q->enabled)return CR_OK;
    if(q->enabled!=1 || q->counter_hz!=CR_COUNTER_HZ || !q->timeout_us ||
       q->timeout_us>5000000 || !q->operation_limit || q->operation_limit>20000 ||
       !q->lease_epoch || !io->ticks || !io->observe || !io->write || !io->read ||
       !io->synchronize)return CR_ARGUMENT;
    if(q->consys_bytes!=CR_CONSYS_BYTES || (q->consys_base&0xffffff) ||
       q->consys_base<0x40000000 || q->consys_base>UINT64_C(0x100000000)-CR_CONSYS_BYTES)return CR_RANGE;
    for(i=0;i<CR_IMAGES;i++) {
        const struct cr_source *s=q->image+i;
        if(s->length!=profiles[i].file_bytes || !pointer_range(s->bytes,s->length))return CR_RANGE;
        if(!s->physical_address || s->physical_address>UINT64_MAX-s->length)return CR_RANGE;
        if(overlap(s->physical_address,s->length,q->consys_base,q->consys_bytes))return CR_OVERLAP;
        for(j=0;j<i;j++)if(overlap(s->physical_address,s->length,q->image[j].physical_address,q->image[j].length))return CR_OVERLAP;
        ptr[4+i]=s->bytes;len[4+i]=s->length;
        for(j=0;j<4+i;j++)if(overlap((uintptr_t)ptr[4+i],len[4+i],(uintptr_t)ptr[j],len[j]))return CR_ARGUMENT;
        /* Checked profiles, rather than caller-selected offsets or sizes. */
        if((uint64_t)profiles[i].offset+s->length-48>=q->consys_bytes ||
           (uint64_t)profiles[i].buildtime_offset+16>q->consys_bytes)return CR_RANGE;
    }
    return CR_OK;
}
int cr_stage(const struct cr_request *q,const struct cr_io *io,
             struct cr_workspace *w,struct cr_report *r)
{
    struct context c;struct cr_sha256 hash;uint8_t digest[32];
    size_t i,at,n;int e=layout(q,io,w,r);
    /* Reject bad layouts without overwriting a possibly aliased input. */
    if(e)return e;
    zero(r,sizeof(*r));r->image=UINT32_MAX;
    if(!q->enabled){r->result=CR_DISABLED;return CR_DISABLED;}
    copy(&w->request,q,sizeof(*q));copy(&w->io,io,sizeof(*io));q=&w->request;
    c.w=w;c.r=r;c.budget=(uint64_t)q->timeout_us*13;c.baseline=0;
    r->began_ticks=r->ended_ticks=w->io.ticks(w->io.context);
    if((e=guard(&c,CR_VALIDATE)))goto out;
    /* Validate ALL headers and full SHA-256 identities before any write. */
    for(i=0;i<CR_IMAGES;i++) {
        const uint8_t *b=q->image[i].bytes;r->image=(uint32_t)i;
        if((e=guard(&c,CR_VALIDATE)))goto out;
        copy(w->header[i],b,48);b=w->header[i];
        if(b[16]!='A'||b[17]!='L'||b[18]!='P'||b[19]!='S'||
           b[20]!=0x8a||b[21]||b[22]!=0x8a||b[23]||b[24]!=0x11||
           (le32(b+24)&0xffffff00)!=(0xf0000000|profiles[i].offset)||
           b[28]||b[29]||b[30]||b[31]!=profiles[i].type){e=CR_HEADER;goto out;}
        cr_sha256_init(&hash);
        /* Bind the saved debug date to the same validated header bytes. */
        cr_sha256_update(&hash,w->header[i],48);r->source_bytes_hashed+=48;
        for(at=48;at<q->image[i].length;at+=n) {
            n=q->image[i].length-at;if(n>CR_CHUNK)n=CR_CHUNK;
            if((e=guard(&c,CR_HASH)))goto out;
            cr_sha256_update(&hash,q->image[i].bytes+at,n);r->source_bytes_hashed+=n;
        }
        cr_sha256_final(&hash,digest);
        if(!equal(digest,profiles[i].file_sha256,32)){e=CR_SOURCE_HASH;goto out;}
        r->validated_images++;
    }
    for(i=0;i<CR_IMAGES;i++) {
        r->image=(uint32_t)i;cr_sha256_init(&hash);
        for(at=48;at<q->image[i].length;at+=n) {
            n=q->image[i].length-at;if(n>CR_CHUNK)n=CR_CHUNK;
            /* Source buffers must remain immutable under the caller's lease.
             * Staged-byte hashing additionally detects a violated contract. */
            if((e=guard(&c,CR_COPY)))goto out;
            copy(w->source,q->image[i].bytes+at,n);
            cr_sha256_update(&hash,w->source,n);
            if((e=transfer(&c,q->consys_base+profiles[i].offset+at-48,n,CR_COPY)))goto out;
        }
        cr_sha256_final(&hash,digest);
        if(!equal(digest,profiles[i].body_sha256,32)){e=CR_SOURCE_CHANGED;goto out;}
        copy(w->source,w->header[i],15);w->source[15]=0;
        if((e=transfer(&c,q->consys_base+profiles[i].buildtime_offset,16,CR_BUILD_TIME)))goto out;
        r->completed_images++;
    }
    e=guard(&c,CR_FINISH);
out:
    {int ended=time_check(&c);if(!e)e=ended;}
    r->result=e;
    return e;
}
