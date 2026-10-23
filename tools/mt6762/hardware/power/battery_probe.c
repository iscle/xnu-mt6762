/* Read-only original IOKit registry probe. No charger, PMIC or registry writes.
 * Inspect named public validity/measurement fields, not device identity. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <time.h>
#include <sys/types.h>
#include <sys/sysctl.h>
#include <errno.h>
#include <string.h>
static void diagnostic(const char *key)
{
    char name[128];
    int value = 0;
    size_t size = sizeof(value);
    snprintf(name, sizeof(name), "kern.redwood.%s", key);
    errno = 0;
    int status = sysctlbyname(name, &value, &size, NULL, 0);
    int error = status ? errno : (size == sizeof(value) ? 0 : EINVAL);
    printf("MT6762_BAT_SYSCTL %s=%d error=%d\n", key, value, error);
}
static void property(CFDictionaryRef properties, CFStringRef key)
{
    CFTypeRef value = CFDictionaryGetValue(properties, key);
    char name[64] = {0};
    CFStringGetCString(key, name, sizeof(name), kCFStringEncodingUTF8);
    if (!value) printf("MT6762_BAT_PROPERTY %s=<absent>\n", name);
    else if (CFGetTypeID(value) == CFBooleanGetTypeID())
        printf("MT6762_BAT_PROPERTY %s=bool:%u\n", name, CFBooleanGetValue(value));
    else if (CFGetTypeID(value) == CFNumberGetTypeID()) {
        /* Kernel publishes signed current as a32-bit OSNumber bit pattern. */
        int64_t raw = 0;
        if (CFNumberGetValue(value, kCFNumberSInt64Type, &raw) &&
            raw >= INT32_MIN && raw <= UINT32_MAX) {
            int32_t number = (int32_t)(raw > INT32_MAX ? raw - INT64_C(4294967296) : raw);
            printf("MT6762_BAT_PROPERTY %s=sint32:%d\n", name, number);
        }
        else printf("MT6762_BAT_PROPERTY %s=<number-conversion-failed>\n", name);
    } else printf("MT6762_BAT_PROPERTY %s=<unexpected-type>\n", name);
}
int main(int argc, char **argv)
{
    unsigned repeats = argc > 1 ? (unsigned)strtoul(argv[1], NULL, 10) : 1;
    unsigned interval_ms = argc > 2 ? (unsigned)strtoul(argv[2], NULL, 10) : 10000;
    if (!repeats || repeats > 256 || !interval_ms || interval_ms > 10000) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    for (unsigned sample = 0; sample < repeats; sample++) {
        io_iterator_t iterator = 0;
        kern_return_t result = IOServiceGetMatchingServices(0,
            IOServiceMatching("IOPMPowerSource"), &iterator);
        struct timespec now = {0};
        int clock_status = clock_gettime(CLOCK_MONOTONIC, &now);
        printf("MT6762_BAT_PROBE iteration=%u readonly=1 status=%#x monotonic_ns=%llu clock_status=%d\n",
            sample, result, (unsigned long long)now.tv_sec * 1000000000ULL + now.tv_nsec, clock_status);
        if (result) return 3;
        io_service_t service;
        unsigned count = 0;
        while (count < 8 && (service = IOIteratorNext(iterator))) {
            io_name_t name = {0}, class_name = {0};
            IORegistryEntryGetName(service, name);
            IOObjectGetClass(service, class_name);
            printf("MT6762_BAT_SERVICE name=%s class=%s\n", name, class_name);
            CFMutableDictionaryRef properties = NULL;
            kern_return_t snapshot_status = IORegistryEntryCreateCFProperties(service, &properties, NULL, 0);
            printf("MT6762_BAT_SNAPSHOT status=%#x\n", snapshot_status);
            const CFStringRef keys[] = {CFSTR("MT6762ValidFields"), CFSTR("BatteryInstalled"),
                CFSTR("ExternalConnected"), CFSTR("IsCharging"), CFSTR("Voltage"),
                CFSTR("AppleRawExternalConnected"), CFSTR("FullyCharged"),
                CFSTR("ExternalChargeCapable"), CFSTR("AdapterDetails"),
                CFSTR("Amperage"), CFSTR("InstantAmperage"), CFSTR("CurrentCapacity"),
                CFSTR("MaxCapacity"), CFSTR("AppleRawCurrentCapacity"),
                CFSTR("AppleRawMaxCapacity"), CFSTR("DesignCapacity"), CFSTR("NominalChargeCapacity"),
                CFSTR("Temperature"), CFSTR("CycleCount"), CFSTR("TimeRemaining"),
                CFSTR("MT6762ReportExpired")};
            if (!snapshot_status && properties) {
                for (unsigned k = 0; k < sizeof(keys) / sizeof(keys[0]); k++) property(properties, keys[k]);
            }
            if (properties) CFRelease(properties);
            IOObjectRelease(service);
            count++;
        }
        IOObjectRelease(iterator);
        printf("MT6762_BAT_COUNT %u\n", count);
        diagnostic("mt6762_power_valid");
        diagnostic("mt6762_adc_voltage_requests");
        diagnostic("mt6762_battery_report_gap_state");
        diagnostic("mt6762_battery_reports_suppressed");
        if (sample + 1 < repeats) usleep(interval_ms * 1000);
    }
    return 0;
}
