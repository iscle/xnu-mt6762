/* SPDX-License-Identifier: MIT
 * Small static PID1 bridge from a RAM bootstrap to unchanged Apple userspace
 * on the explicitly bounded, read-only native eMMC system slice. No libc,
 * filesystem writes, card commands, Apple executable patches or retries.
 */
typedef unsigned long usize;
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
static usize length(const char *p) {usize n=0;while(p[n])n++;return n;}
static int console;
static void print(const char *s)
{call6(4,console,(long)s,length(s),0,0,0);}
static void outcome(const char *step,long result)
{
    char digits[24];usize n=0;
    print("MT6762_DESKTOP ");print(step);print(" result=");
    if(result<0){print("-");result=-result;}
    do{digits[n++]='0'+result%10;result/=10;}while(result);
    while(n)call6(4,console,(long)&digits[--n],1,0,0,0);
    print("\n");
}
__attribute__((noreturn)) static void stop(const char *step,long error)
{
    outcome(step,error);print("MT6762_DESKTOP stopped\n");
    for(;;){char c;call6(3,console,(long)&c,1,0,0,0);}
}
__attribute__((used,noreturn)) static void desktop_main(const usize *initial_stack)
{
    /* Keep the original Darwin argc/argv stack available to this C entry.
     * This bootstrap currently supplies its own argv to the existing init. */
    (void)initial_stack;
    console=(int)call6(5,(long)"/dev/console",2,0,0,0,0);
    if(console<0)for(;;)__asm__ volatile("yield");
    for(long fd=0;fd<3;fd++)call6(90,console,fd,0,0,0,0); /* dup2 */
    long result=call6(20,0,0,0,0,0,0);
    if(result!=1)stop("pid",result);
    print("MT6762_DESKTOP bootstrap ready\n");
    /* This port's APFS mount ABI takes a device path, not Apple's opaque ABI. */
    result=call6(167,(long)"apfs",(long)"/newroot",1,(long)"/dev/mtkios0",0,0);
    if(result)stop("mount",result);
    outcome("system_mounted",0);
    const char key[]="kern.redwood_switch_root",value[]="/newroot redwood";
    result=call6(274,(long)key,sizeof(key)-1,0,0,(long)value,sizeof(value)-1);
    if(result)stop("switch_root",result);
    result=call6(12,(long)"/",0,0,0,0,0);
    if(result)stop("chdir",result);
    print("MT6762_DESKTOP system root active; starting existing init\n");
    const char *argv[]={"/redwood/sbin/init",0};
    const char *env[]={"PATH=/redwood/bin:/usr/bin:/bin:/usr/sbin:/sbin",0};
    result=call6(59,(long)argv[0],(long)argv,(long)env,0,0,0);
    stop("exec_init",result);
}

/* LC_UNIXTHREAD enters with Darwin's pointer-aligned argc stack, not a C call.
 * Capture27 reached the old C prologue with SP ending in 8 and took
 * EXC_ARM_SP_ALIGN at its first STP. Preserve the untouched argument area in
 * x0, align the working stack before any stack access, and never return. */
__attribute__((naked,noreturn)) void start(void)
{
    __asm__ volatile("mov x0, sp\n\t"
                     "and x9, x0, #0xfffffffffffffff0\n\t"
                     "mov sp, x9\n\t"
                     "b _desktop_main\n\t");
}
