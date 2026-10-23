/* QEMU-only display lifecycle request diagnostic. No direct MMIO or IOKit writes. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static bool flag(io_registry_entry_t entry, CFStringRef key)
{
    CFTypeRef value = IORegistryEntryCreateCFProperty(entry, key, NULL, 0);
    bool valid = value && CFGetTypeID(value) == CFDataGetTypeID() &&
        CFDataGetLength(value) == 4;
    if (valid) {
        const UInt8 *bytes = CFDataGetBytePtr(value);
        valid = bytes[0] == 1 && !bytes[1] && !bytes[2] && !bytes[3];
    }
    if (value) CFRelease(value);
    return valid;
}
static bool is_lab(void)
{
    io_registry_entry_t entry = IORegistryEntryFromPath(0,
        "IODeviceTree:/chosen/mt6762-handoff");
    if (!entry) return false;
    bool valid = flag(entry, CFSTR("version")) && flag(entry, CFSTR("native-io")) &&
        flag(entry, CFSTR("lab-fixture"));
    IOObjectRelease(entry);
    return valid;
}
static int native_level(void)
{
    io_service_t service = IOServiceGetMatchingService(0, IOServiceMatching("AppleARMBacklight"));
    if (!service) return -1;
    CFTypeRef parameters = IORegistryEntryCreateCFProperty(service,
        CFSTR("IODisplayParameters"), NULL, 0);
    int level = -1;
    if (parameters && CFGetTypeID(parameters) == CFDictionaryGetTypeID()) {
        CFTypeRef brightness = CFDictionaryGetValue(parameters, CFSTR("brightness"));
        if (brightness && CFGetTypeID(brightness) == CFDictionaryGetTypeID()) {
            CFTypeRef value = CFDictionaryGetValue(brightness, CFSTR("value"));
            if (value && CFGetTypeID(value) == CFNumberGetTypeID())
                CFNumberGetValue(value, kCFNumberIntType, &level);
        }
    }
    if (parameters) CFRelease(parameters);
    IOObjectRelease(service);
    return level;
}
static int desired_level(void)
{
    io_service_t service = IOServiceGetMatchingService(0, IOServiceMatching("AppleARMBacklight"));
    if (!service) return -1;
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, CFSTR("MT6762DesiredBrightness"), NULL, 0);
    int level = -1;
    if (value && CFGetTypeID(value) == CFNumberGetTypeID())
        CFNumberGetValue(value, kCFNumberIntType, &level);
    if (value) CFRelease(value);
    IOObjectRelease(service);
    return level;
}
/* Uses only original framework APIs; requests are restricted to a lab ADT. */
int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 2 || strcmp(argv[1], "--qemu-lab") || !is_lab()) return 2;
    unsigned delay = argc > 2 ? (unsigned)strtoul(argv[2], NULL, 10) : 45;
    if (delay > 600) return 2;
    printf("MT6762_POWER_WAIT seconds=%u\n", delay);
    sleep(delay);
    void *bks = dlopen("/System/Library/PrivateFrameworks/BackBoardServices.framework/BackBoardServices", RTLD_NOW);
    void *iomfb = dlopen("/System/Library/PrivateFrameworks/IOMobileFramebuffer.framework/IOMobileFramebuffer", RTLD_NOW);
    if (!bks || !iomfb) return 3;
    int32_t (*set)(float) = dlsym(bks, "BKSDisplayBrightnessSetWithImplicitTransaction");
    float (*get)(void) = dlsym(bks, "BKSDisplayBrightnessGetCurrent");
    bool (*available)(void) = dlsym(bks, "BKSDisplayBrightnessIsBrightnessLevelControlAvailable");
    int32_t (*main_display)(void **) = dlsym(iomfb, "IOMobileFramebufferGetMainDisplay");
    int32_t (*power)(void *, uint32_t) = dlsym(iomfb, "IOMobileFramebufferRequestPowerChange");
    if (!set || !get || !available || !main_display || !power) return 4;
    bool ready = false;
    for (unsigned i = 0; i < 30; i++) { ready = available(); if (ready) break; sleep(2); }
    if (!ready) return 5;
    void *display = NULL;
    int32_t status = main_display(&display);
    printf("MT6762_POWER_OPEN status=%#x present=%u\n", status, display != NULL);
    if (status || !display) return 6;
    float original = get();
    if (!(original >= 0 && original <= 1)) return 7;
    status = set(0.25f);
    sleep(4);
    printf("MT6762_POWER_BEFORE status=%#x published=%d\n", status, native_level());
    status = power(display, 0);
    sleep(4);
    printf("MT6762_POWER_OFF status=%#x published=%d desired=%d\n", status, native_level(), desired_level());
    if (status) return 8;
    status = set(0.75f);
    sleep(4);
    printf("MT6762_POWER_DEFERRED status=%#x published=%d desired=%d logical=%.6f\n", status, native_level(), desired_level(), get());
    status = power(display, 0);
    printf("MT6762_POWER_DUPLICATE_OFF status=%#x published=%d desired=%d\n", status, native_level(), desired_level());
    status = power(display, 1);
    sleep(4);
    printf("MT6762_POWER_ON status=%#x published=%d desired=%d logical=%.6f\n", status, native_level(), desired_level(), get());
    if (status) return 9;
    status = set(original);
    sleep(4);
    printf("MT6762_POWER_RESTORE status=%#x published=%d desired=%d logical=%.6f\n", status, native_level(), desired_level(), get());
    puts("MT6762_POWER_DONE require independent PWM and framebuffer evidence");
    return status ? 10 : 0;
}
