/* Read-only original IOKit registry probe. No charger, PMIC or registry writes.
 * Inspect named public validity/measurement fields, not device identity. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
static void property(io_service_t service, CFStringRef key)
{
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key, NULL, 0);
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
    if (value) CFRelease(value);
}
int main(int argc, char **argv)
{
    unsigned repeats = argc > 1 ? (unsigned)strtoul(argv[1], NULL, 10) : 1;
    if (!repeats || repeats > 16) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    for (unsigned sample = 0; sample < repeats; sample++) {
        io_iterator_t iterator = 0;
        kern_return_t result = IOServiceGetMatchingServices(0,
            IOServiceMatching("IOPMPowerSource"), &iterator);
        printf("MT6762_BAT_PROBE iteration=%u readonly=1 status=%#x\n", sample, result);
        if (result) return 3;
        io_service_t service;
        unsigned count = 0;
        while (count < 8 && (service = IOIteratorNext(iterator))) {
            io_name_t name = {0}, class_name = {0};
            IORegistryEntryGetName(service, name);
            IOObjectGetClass(service, class_name);
            printf("MT6762_BAT_SERVICE name=%s class=%s\n", name, class_name);
            const CFStringRef keys[] = {CFSTR("MT6762ValidFields"), CFSTR("BatteryInstalled"),
                CFSTR("ExternalConnected"), CFSTR("IsCharging"), CFSTR("Voltage"),
                CFSTR("Amperage"), CFSTR("InstantAmperage"), CFSTR("CurrentCapacity"),
                CFSTR("MaxCapacity"), CFSTR("AppleRawCurrentCapacity"),
                CFSTR("AppleRawMaxCapacity"), CFSTR("DesignCapacity"),
                CFSTR("Temperature"), CFSTR("CycleCount"), CFSTR("TimeRemaining")};
            for (unsigned k = 0; k < sizeof(keys) / sizeof(keys[0]); k++) property(service, keys[k]);
            IOObjectRelease(service);
            count++;
        }
        IOObjectRelease(iterator);
        printf("MT6762_BAT_COUNT %u\n", count);
        if (sample + 1 < repeats) sleep(10);
    }
    return 0;
}
