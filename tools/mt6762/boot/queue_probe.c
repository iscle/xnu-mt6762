/* SPDX-License-Identifier: MIT
 * Static Darwin PID1 observer for the native input queue. No event injection,
 * dyld, libc, Apple executable or shared cache is used by this probe.
 */
typedef unsigned long u64;
typedef unsigned int u32;
struct sample { u64 time; u32 type, finger, x, y; };
_Static_assert(sizeof(struct sample) == 24, "redwood queue ABI");
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
static void observe(int fd)
{
    static const char *const fields[] = {
        "mt6762_pmic_id", "mt6762_power_valid", "mt6762_power_errors",
        "mt6762_battery_adc_mv", "mt6762_ntc_adc_mv",
        "mt6762_adc_voltage_samples", "mt6762_adc_ntc_samples",
        "mt6762_charger_control_safe", "mt6762_charger_state",
        "mt6762_sspm_alive", "mt6762_sspm_fault"
    };
    for (unsigned i = 0; i < sizeof(fields) / sizeof(fields[0]); i++) {
        char name[96], line[192], *end = text(name, "kern.redwood.");
        end = text(end, fields[i]); *end = 0;
        int value = 0; u64 size = sizeof(value);
        /* Darwin syscalls.master274, read-only new=NULL/newlen=0. */
        long error = call6(274, (long)name, end-name, (long)&value, (long)&size, 0, 0);
        char *p = text(line, "MT6762_SYSCTL "); p = text(p, fields[i]); *p++ = '=';
        if (value < 0) *p++ = '-';
        p = decimal(p, value < 0 ? -(long)value : value);
        p = text(p, " error="); if (error < 0) *p++ = '-';
        p = decimal(p, error < 0 ? -error : error); *p++ = '\n';
        call3(4, fd, (long)line, p-line);
    }
}
void start(void)
{
    int console = call3(5, (long)"/dev/console", 2, 0);
    int queue = call3(5, (long)"/dev/redwood-touch", 0, 0);
    print(console, queue >= 0 ? "MT6762_QUEUE_READY\n" : "MT6762_QUEUE_OPEN_FAILED\n");
    observe(console);
    unsigned records = 0;
    for (;;) {
        struct sample s;
        if (call3(3, queue, (long)&s, sizeof(s)) == sizeof(s)) {
            char line[192], *p = text(line, "MT6762_QUEUE type=");
            p = decimal(p, s.type); p = text(p, " finger="); p = decimal(p, s.finger);
            p = text(p, " x="); p = decimal(p, s.x); p = text(p, " y="); p = decimal(p, s.y);
            p = text(p, " time="); p = decimal(p, s.time); *p++ = '\n';
            call3(4, console, (long)line, p - line);
            if (s.type >= 4 || (++records % 16) == 0) observe(console);
        } else {
            print(console, "MT6762_QUEUE_READ_FAILED\n");
            /* Do not exit PID1 or spin if opening/reading the device failed. */
            char byte;
            call3(3, console, (long)&byte, 1);
        }
    }
}
