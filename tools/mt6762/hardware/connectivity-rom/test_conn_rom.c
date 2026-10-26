/* SPDX-License-Identifier: MIT
 * Executes the actual core against a modeled cache/RAM consumer, never MMIO.
 */
#include "conn_rom.h"
#include "sha256.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum fault { F_NONE,F_WRITE,F_SHORT_WRITE,F_READ,F_SHORT_READ,F_MISMATCH,
    F_PUBLISH,F_INVALIDATE,F_ADMIT,F_STATE,F_LATE,F_SOURCE,F_BACKWARDS };
struct fixture {
    uint8_t *dram,*cache,*file[3];
    struct cr_request request;struct cr_io io;
    struct cr_workspace workspace;struct cr_report report;
    uint64_t tick,step;unsigned tick_calls;
    enum fault fault;enum cr_phase fault_phase;unsigned target,state_field,fired;
    unsigned observations,writes,reads,publishes,invalidates,sequence;
    uint64_t pending;size_t pending_n;
    unsigned expected_image;size_t expected_at;
    struct cr_live live;
};
static uint64_t ticks(void *v)
{
    struct fixture *f=v;f->tick_calls++;
    if(f->fault==F_BACKWARDS && f->tick_calls==10){f->tick-=1000;f->fired++;}
    f->tick+=f->step;return f->tick;
}
static int observe(void *v,enum cr_phase phase,struct cr_live *s)
{
    struct fixture *f=v;f->observations++;*s=f->live;
    assert(!f->fired || f->fault==F_SOURCE);
    if(f->fault==F_SOURCE && phase==CR_COPY && !f->fired) {
        f->file[0][2000]^=1;f->fired++;return 0;
    }
    if((f->fault==F_ADMIT || f->fault==F_STATE || f->fault==F_LATE) &&
       phase==f->fault_phase && !f->fired) {
        f->fired++;
        if(f->fault==F_ADMIT)return -91;
        if(f->fault==F_LATE){f->tick+=UINT64_C(13000000)*6;return 0;}
        switch(f->state_field) {
        case 0:s->lease_epoch++;break;
        case 1:s->owned_base+=0x1000000;break;
        case 2:s->owned_bytes--;break;
        case 3:s->rgu_reset&=~0x1000U;break;
        case 4:s->spm_control|=0x10;break;
        case 5:s->power_status&=~2U;break;
        case 6:s->power_status2&=~2U;break;
        case 7:s->ip_id^=1;break;
        case 8:s->fw_version|=1;break;
        case 9:s->emi_remap^=1;break;
        case 10:s->hw_version^=1;break;
        case 11:s->fw_version^=0x100;break;
        default:assert(0);
        }
    }
    return 0;
}
static size_t offset(struct fixture *f,uint64_t pa,size_t n)
{
    assert(pa>=f->request.consys_base && n && n<=CR_CHUNK);
    assert(pa-f->request.consys_base<=CR_CONSYS_BYTES-n);
    return (size_t)(pa-f->request.consys_base);
}
static int write_ram(void *v,uint64_t pa,const uint8_t *data,size_t n,size_t *done)
{
    struct fixture *f=v;const struct cr_profile *p;size_t at=offset(f,pa,n),expected_n;
    assert(!f->fired || f->fault==F_SOURCE);
    assert(f->sequence==0 && f->expected_image<3);p=cr_profile_at(f->expected_image);
    if(f->expected_at==p->file_bytes-48) {
        assert(at==p->buildtime_offset && n==16);
        assert(!memcmp(data,f->file[f->expected_image],15) && data[15]==0);
        f->expected_image++;f->expected_at=0;
    } else {
        expected_n=p->file_bytes-48-f->expected_at;if(expected_n>CR_CHUNK)expected_n=CR_CHUNK;
        assert(at==p->offset+f->expected_at && n==expected_n);
        assert(!memcmp(data,f->file[f->expected_image]+48+f->expected_at,n));
        f->expected_at+=n;
    }
    f->writes++;f->pending=pa;f->pending_n=n;f->sequence=1;
    *done=n;
    if(f->writes==f->target && f->fault==F_SHORT_WRITE){*done=n-1;f->fired++;}
    memcpy(f->cache+at,data,*done);
    if(f->writes==f->target && f->fault==F_WRITE){f->fired++;return -92;}
    return 0;
}
static int sync_ram(void *v,uint64_t pa,size_t n,enum cr_cache_action action)
{
    struct fixture *f=v;size_t at=offset(f,pa,n);
    assert(!f->fired || f->fault==F_SOURCE);
    assert(pa==f->pending && n==f->pending_n);
    if(action==CR_CACHE_PUBLISH) {
        assert(f->sequence==1);f->publishes++;
        if(f->fault==F_PUBLISH && f->publishes==f->target){f->fired++;return -93;}
        memcpy(f->dram+at,f->cache+at,n);f->sequence=2;
    } else {
        assert(action==CR_CACHE_PREPARE_READ && f->sequence==2);f->invalidates++;
        if(f->fault==F_INVALIDATE && f->invalidates==f->target){f->fired++;return -94;}
        memset(f->cache+at,0,n); /* A read of stale/write cache cannot pass. */
        f->sequence=3;
    }
    return 0;
}
static int read_ram(void *v,uint64_t pa,uint8_t *data,size_t n,size_t *done)
{
    struct fixture *f=v;size_t at=offset(f,pa,n);
    assert(!f->fired || f->fault==F_SOURCE);
    assert(f->sequence==3 && pa==f->pending && n==f->pending_n);
    f->reads++;*done=n;
    if(f->fault==F_SHORT_READ && f->reads==f->target){*done=n-1;f->fired++;}
    memcpy(data,f->dram+at,*done);
    if(f->fault==F_MISMATCH && f->reads==f->target){data[n/2]^=1;f->fired++;}
    if(f->fault==F_READ && f->reads==f->target){f->fired++;return -95;}
    f->sequence=0;return 0;
}
static void setup(struct fixture *f)
{
    unsigned i;uint8_t *dram=f->dram,*cache=f->cache,*files[3];
    for(i=0;i<3;i++)files[i]=f->file[i];
    memset(f,0,sizeof(*f));f->dram=dram;f->cache=cache;
    memset(f->dram,0xa5,CR_CONSYS_BYTES);memset(f->cache,0xcc,CR_CONSYS_BYTES);
    f->request=(struct cr_request){.enabled=1,.counter_hz=CR_COUNTER_HZ,
        .timeout_us=5000000,.operation_limit=20000,.lease_epoch=7,
        .consys_base=0xa0000000,.consys_bytes=CR_CONSYS_BYTES};
    for(i=0;i<3;i++) {
        f->file[i]=files[i];f->request.image[i]=(struct cr_source){files[i],cr_profile_at(i)->file_bytes,UINT64_C(0x120000000)+i*0x100000};
    }
    f->live=(struct cr_live){.lease_epoch=7,.owned_base=0xa0000000,.owned_bytes=CR_CONSYS_BYTES,
        .rgu_reset=0x5000,.spm_control=0xd,.power_status=0x434e,.power_status2=0x434e,
        .ip_id=0x10020300,.hw_version=0x8a10,.fw_version=0x8a00,.emi_remap=0xa0};
    f->io=(struct cr_io){f,ticks,observe,write_ram,read_ram,sync_ram};
    f->step=1;f->target=1;
}
static int run(struct fixture *f) { return cr_stage(&f->request,&f->io,&f->workspace,&f->report); }
static void hash_test(const char *text,const char *expected)
{
    struct cr_sha256 s;uint8_t out[32];char hex[65];size_t i;
    cr_sha256_init(&s);
    for(i=0;text[i];i++)cr_sha256_update(&s,(const uint8_t *)text+i,1);
    cr_sha256_final(&s,out);
    for(i=0;i<32;i++)sprintf(hex+2*i,"%02x",out[i]);
    assert(!strcmp(hex,expected));
}
static void primitive_tests(void)
{
    struct cr_request q={0};struct cr_io io={0};struct cr_workspace w;struct cr_report r;
    hash_test("","e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    hash_test("abc","ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    hash_test("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq","248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
    assert(cr_stage(&q,&io,&w,&r)==CR_DISABLED && r.operations==0);
    assert(cr_stage(0,&io,&w,&r)==CR_ARGUMENT);
    assert(cr_stage(&q,&io,&w,(void *)&q)==CR_ARGUMENT);
    assert(!cr_profile_at(3));
    puts("SHA-256 known vectors, disabled/no-callback and bad-argument tests PASS");
}
static void check_destination(struct fixture *f)
{
    size_t at,i,n;unsigned ranges=0;
    for(at=0;at<CR_CONSYS_BYTES;at++) {
        int found=0;
        for(i=0;i<3;i++) {
            const struct cr_profile *p=cr_profile_at(i);n=p->file_bytes-48;
            if(at>=p->offset && at<p->offset+n){assert(f->dram[at]==f->file[i][48+at-p->offset]);found=1;break;}
            if(at>=p->buildtime_offset && at<p->buildtime_offset+16){
                assert(f->dram[at]==(at==p->buildtime_offset+15?0:f->file[i][at-p->buildtime_offset]));found=1;break;
            }
        }
        if(!found)assert(f->dram[at]==0xa5);else ranges++;
    }
    assert(ranges==571037+196160+105892+48);
}
int main(int argc,char **argv)
{
    struct fixture *f;unsigned i,j,total_writes,tests=0;
    static const enum cr_phase phases[]={CR_VALIDATE,CR_HASH,CR_COPY,CR_PUBLISH,CR_INVALIDATE,CR_READBACK_PHASE,CR_BUILD_TIME,CR_FINISH};
    primitive_tests();
    if(argc==1){puts("SKIP exact-firmware staging tests: pass BT, Wi-Fi and MCU private original paths");return 0;}
    assert(argc==4);f=calloc(1,sizeof(*f));assert(f);
    f->dram=malloc(CR_CONSYS_BYTES);f->cache=malloc(CR_CONSYS_BYTES);assert(f->dram && f->cache);
    for(i=0;i<3;i++) {
        FILE *in=fopen(argv[i+1],"rb");size_t n=cr_profile_at(i)->file_bytes;assert(in);
        f->file[i]=malloc(n);assert(f->file[i]);assert(fread(f->file[i],1,n,in)==n);
        assert(fgetc(in)==EOF);fclose(in);
    }
    setup(f);assert(run(f)==CR_OK);total_writes=f->writes;tests++;
    assert(f->report.validated_images==3 && f->report.completed_images==3 && f->expected_image==3);
    assert(f->report.bytes_written==873137 && f->report.bytes_verified==873137);
    assert(f->report.source_bytes_hashed==873233 && f->report.writes==total_writes);
    check_destination(f);
    printf("Exact firmware success: %u transfers, %u observations, %llu verified bytes\n",total_writes,f->observations,(unsigned long long)f->report.bytes_verified);
    /* Each later image must also authenticate before ANY destination writes. */
    for(i=0;i<3;i++) {
        setup(f);f->file[i][100]^=1;assert(run(f)==CR_SOURCE_HASH && !f->writes);f->file[i][100]^=1;tests++;
        setup(f);f->file[i][0]^=1;assert(run(f)==CR_SOURCE_HASH && !f->writes);f->file[i][0]^=1;tests++;
        setup(f);f->file[i][40]^=1;assert(run(f)==CR_SOURCE_HASH && !f->writes);f->file[i][40]^=1;tests++;
        setup(f);f->file[i][24]^=1;assert(run(f)==CR_HEADER && !f->writes);f->file[i][24]^=1;tests++;
    }
    /* Callback faults/short operations at early, middle and final transfers. */
    for(i=F_WRITE;i<=F_INVALIDATE;i++)for(j=0;j<3;j++) {
        int expected=(i==F_SHORT_WRITE || i==F_SHORT_READ)?CR_SHORT:(i==F_MISMATCH?CR_READBACK:CR_IO);
        setup(f);f->fault=(enum fault)i;f->target=j==0?1:(j==1?total_writes/2:total_writes);
        assert(run(f)==expected && f->fired==1);assert(f->writes==f->target);tests++;
    }
    for(i=0;i<sizeof(phases)/sizeof(phases[0]);i++) {
        setup(f);f->fault=F_ADMIT;f->fault_phase=phases[i];assert(run(f)==CR_ADMISSION && f->fired==1);tests++;
        setup(f);f->fault=F_LATE;f->fault_phase=phases[i];assert(run(f)==CR_TIMEOUT && f->fired==1);tests++;
    }
    for(i=0;i<12;i++) {
        setup(f);f->fault=F_STATE;f->fault_phase=CR_COPY;f->state_field=i;
        assert(run(f)==CR_STATE && !f->writes);tests++;
        setup(f);f->fault=F_STATE;f->fault_phase=CR_INVALIDATE;f->state_field=i;
        assert(run(f)==CR_STATE && f->writes==1 && !f->reads);tests++;
    }
    setup(f);f->step=0;f->request.operation_limit=10;assert(run(f)==CR_LIMIT && f->observations==10 && !f->writes);tests++;
    setup(f);f->tick=UINT64_MAX-100;assert(run(f)==CR_OK);tests++;
    setup(f);f->fault=F_BACKWARDS;assert(run(f)==CR_TIMEOUT && !f->writes);tests++;
    setup(f);f->fault=F_SOURCE;assert(run(f)==CR_SOURCE_CHANGED && f->report.completed_images==0);
    assert(f->report.bytes_written==571037);f->file[0][2000]^=1;tests++;
    /* Invalid ownership/address/size/virtual-alias layouts call no callbacks. */
    for(i=0;i<11;i++) {
        int expected=CR_RANGE;setup(f);
        switch(i) {
        case 0:f->request.consys_base++;break;
        case 1:f->request.consys_base=UINT64_C(0x100000000);break;
        case 2:f->request.consys_bytes--;break;
        case 3:f->request.image[0].physical_address=f->request.consys_base;expected=CR_OVERLAP;break;
        case 4:f->request.image[1].physical_address=f->request.image[0].physical_address+1;expected=CR_OVERLAP;break;
        case 5:f->request.image[0].physical_address=UINT64_MAX-1;break;
        case 6:f->request.image[0].length--;break;
        case 7:f->request.image[0].bytes=(void *)&f->report;expected=CR_ARGUMENT;break;
        case 8:f->request.image[1].bytes=f->file[0];expected=CR_ARGUMENT;break;
        case 9:f->request.counter_hz=24000000;expected=CR_ARGUMENT;break;
        case 10:f->request.enabled=2;expected=CR_ARGUMENT;break;
        }
        assert(run(f)==expected && !f->observations && !f->writes);tests++;
    }
    printf("Actual core/stateful cache+RAM consumer: %u exact-image scenarios PASS\n",tests);
    printf("Host ABI: workspace %zu bytes, report %zu bytes\n",sizeof(f->workspace),sizeof(f->report));
    for(i=0;i<3;i++)free(f->file[i]);
    free(f->dram);free(f->cache);free(f);
    return 0;
}
