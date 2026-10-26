/* SPDX-License-Identifier: MIT
 * Static Darwin PID1 observer for the opt-in generated RPC selftest. No Apple binaries or libc. */
typedef unsigned long u64;
typedef unsigned int u32;
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

static void diagnostics(int console, unsigned pass)
{
    static const char *const keys[]={"mt6762_iig_test_result","mt6762_iig_test_cases"};
    for(unsigned i=0;i<sizeof(keys)/sizeof(keys[0]);i++) {
        char name[96],line[192],*end=text(name,"kern.hakios.");
        end=text(end,keys[i]);*end=0;int value=0;u64 size=sizeof(value);
        long error=call6(274,(long)name,end-name,(long)&value,(long)&size,0,0);
        char *p=text(line,"MT6762_IIG_SYSCTL pass=");p=decimal(p,pass);*p++=' ';
        p=text(p,keys[i]);*p++='=';
        if(value<0)*p++='-';p=decimal(p,value<0?-(long)value:value);
        p=text(p," error=");if(error<0)*p++='-';p=decimal(p,error<0?-error:error);
        p=text(p," size=");p=decimal(p,size);*p++='\n';
        call3(4,console,(long)line,p-line);
    }
}
void start(void)
{
    int console=call3(5,(long)"/dev/console",2,0);
    print(console,"MT6762_IIG_PROBE_READY\n");
    diagnostics(console,1);
    diagnostics(console,2);
    print(console,"MT6762_IIG_PROBE_DONE\n");
    for(;;) {char byte;call3(3,console,(long)&byte,1);}
}
