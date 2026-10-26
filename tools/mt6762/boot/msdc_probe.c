/* SPDX-License-Identifier: MIT
 * Static Darwin PID1 read-only MSDC observer. No Apple binaries or libc. */
typedef unsigned long u64;
typedef unsigned int u32;
#ifndef MSDC_PROBE_IOS_SLICE
#define MSDC_PROBE_IOS_SLICE 0
#endif
static const char *raw_device=MSDC_PROBE_IOS_SLICE?"/dev/rmtkios0":"/dev/rmtkemmc0";
static const char *block_device=MSDC_PROBE_IOS_SLICE?"/dev/mtkios0":"/dev/mtkemmc0";
static long call3(long number, long a, long b, long c)
{
    register long x16 __asm__("x16") = number;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    unsigned error;
    __asm__ volatile("svc #0x80\n\tcset %w2, cs" : "+r"(x0), "+r"(x1), "=r"(error)
        : "r"(x16), "r"(x2) : "memory", "cc");
    return error ? -x0 : x0;
}
static long call6(long number, long a, long b, long c, long d, long e, long f)
{
    register long x16 __asm__("x16") = number;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    register long x4 __asm__("x4") = e;
    register long x5 __asm__("x5") = f;
    unsigned error;
    __asm__ volatile("svc #0x80\n\tcset %w2, cs" : "+r"(x0), "+r"(x1), "=r"(error)
        : "r"(x16), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory", "cc");
    return error ? -x0 : x0;
}
static char *text(char *p, const char *s) { while (*s) *p++ = *s++; return p; }
static char *decimal(char *p, u64 n)
{
    char digits[24]; unsigned count = 0;
    do { digits[count++] = '0' + n % 10; n /= 10; } while (n);
    while (count) *p++ = digits[--count];
    return p;
}
static void print(int fd, const char *s)
{
    const char *p = s; while (*p) p++;
    call3(4, fd, (long)s, p - s);
}

static void scalar(int console,const char *key,long value)
{
    char line[192],*p=text(line,"MT6762_MSDC ");p=text(p,key);*p++='=';
    if(value<0)*p++='-';p=decimal(p,value<0?-value:value);*p++='\n';
    call3(4,console,(long)line,p-line);
}
static void pause_us(unsigned microseconds)
{
    struct {long seconds;int micros;int padding;} timeout={0,(int)microseconds,0};
    call6(93,0,0,0,0,(long)&timeout,0);
}
static u32 hash(const unsigned char *data,unsigned bytes)
{
    u32 value=2166136261u;
    for(unsigned i=0;i<bytes;i++)value=(value^data[i])*16777619u;
    return value;
}
static void read_sector(int console,int fd,const char *kind,u64 lba)
{
    unsigned char data[512];for(unsigned i=0;i<512;i++)data[i]=0xa5;
    long seek=call3(199,fd,lba*512,0);
    long result=seek==(long)(lba*512)?call3(3,fd,(long)data,512):seek;
    char line[192],*p=text(line,"MT6762_MSDC_READ kind=");p=text(p,kind);
    p=text(p," lba=");p=decimal(p,lba);p=text(p," result=");
    if(result<0)*p++='-';p=decimal(p,result<0?-result:result);
    p=text(p," fnv1a=");p=decimal(p,hash(data,512));*p++='\n';
    call3(4,console,(long)line,p-line);
}
static void read_range(int console,int fd,u64 offset,unsigned count)
{
    static unsigned char data[128*1024];
    if(count>sizeof(data))return;
    for(unsigned i=0;i<count;i++)data[i]=0xa5;
    long seek=call3(199,fd,offset,0);
    long result=seek==(long)offset?call3(3,fd,(long)data,count):seek;
    char line[192],*p=text(line,"MT6762_MSDC_RANGE offset=");p=decimal(p,offset);
    p=text(p," count=");p=decimal(p,count);p=text(p," result=");
    if(result<0)*p++='-';p=decimal(p,result<0?-result:result);
    p=text(p," fnv1a=");p=decimal(p,hash(data,count));*p++='\n';
    call3(4,console,(long)line,p-line);
}
static void diagnostics(int console)
{
    static const char *const keys[]={"mt6762_msdc_ready","mt6762_msdc_fault",
        "mt6762_msdc_last_error","mt6762_msdc_reads","mt6762_msdc_sectors"};
    for(unsigned i=0;i<sizeof(keys)/sizeof(keys[0]);i++) {
        char name[96],line[192],*end=text(name,"kern.redwood.");
        end=text(end,keys[i]);*end=0;int value=0;u64 size=sizeof(value);
        long error=call6(274,(long)name,end-name,(long)&value,(long)&size,0,0);
        char *p=text(line,"MT6762_MSDC_SYSCTL ");p=text(p,keys[i]);*p++='=';
        if(value<0)*p++='-';p=decimal(p,value<0?-(long)value:value);
        p=text(p," error=");if(error<0)*p++='-';p=decimal(p,error<0?-error:error);*p++='\n';
        call3(4,console,(long)line,p-line);
    }
}
void start(void)
{
    int console=call3(5,(long)"/dev/console",2,0);
    print(console,"MT6762_MSDC_PROBE_READY readonly=1\n");
    scalar(console,"ios_slice",MSDC_PROBE_IOS_SLICE);
    int fd=call3(5,(long)raw_device,0,0);
    scalar(console,"char_open",fd);
    if(fd>=0) {
        u32 size=0,writable=1;u64 count=0;
        scalar(console,"blocksize_error",call3(54,fd,0x40046418,(long)&size));
        scalar(console,"blockcount_error",call3(54,fd,0x40086419,(long)&count));
        scalar(console,"writable_error",call3(54,fd,0x4004641d,(long)&writable));
        scalar(console,"blocksize",size);scalar(console,"blockcount",count);
        scalar(console,"writable",writable);
        int writefd=call3(5,(long)raw_device,1,0);
        scalar(console,"write_open",writefd);
        if(writefd>=0)call3(6,writefd,0,0); /* Never issue a storage write. */
        if(size==512 && count>0 && count<=0xffffffffu) {
            read_sector(console,fd,"char",0);
            pause_us(250000);
            if(count>1)read_sector(console,fd,"char",1);
            pause_us(250000);
            read_sector(console,fd,"char",count-1);
            int block=call3(5,(long)block_device,0,0);
            scalar(console,"block_open",block);
            if(block>=0) {read_sector(console,block,"block",0);call3(6,block,0,0);}
            scalar(console,"negative_seek",call3(199,fd,-1,0));
            unsigned char untouched=0xa5;
            scalar(console,"negative_read",call3(3,fd,(long)&untouched,1));
            scalar(console,"negative_buffer",untouched);
            if(count>1)read_range(console,fd,480,64);
            if(MSDC_PROBE_IOS_SLICE && count>=256)read_range(console,fd,0,128*1024);
            read_range(console,fd,count*512-16,32);
            read_range(console,fd,count*512,512);
            read_range(console,fd,(count+1)*512,512);
        }
        call3(6,fd,0,0);
    }
    diagnostics(console);
    print(console,"MT6762_MSDC_PROBE_DONE\n");
    for(;;) {char byte;call3(3,console,(long)&byte,1);}
}
