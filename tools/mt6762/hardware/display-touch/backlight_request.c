/* QEMU laboratory diagnostic, not a physical-device utility.
 * Calls ORIGINAL20F66 BackBoardServices exports through its Mach service.
 * No Apple patching and no IORegistryEntrySetCFProperties/PWM write here.
 * Requires the explicit synthetic ADT lab-fixture contract and --qemu-lab.
 */
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
int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 2 || strcmp(argv[1], "--qemu-lab")) return 2;
    if (!is_lab()) {
        puts("MT6762_BKS_ABORT synthetic ADT contract absent");
        return 3;
    }
    unsigned delay = argc > 2 ? (unsigned)strtoul(argv[2], NULL, 10) : 45;
    unsigned hold = argc > 3 ? (unsigned)strtoul(argv[3], NULL, 10) : 4;
    if (delay > 600 || hold < 4 || hold > 180) return 2;
    printf("MT6762_BKS_WAIT seconds=%u hold=%u uid=%u\n", delay, hold, getuid());
    sleep(delay);
    void *framework = dlopen("/System/Library/PrivateFrameworks/BackBoardServices.framework/BackBoardServices", RTLD_NOW);
    if (!framework) {printf("MT6762_BKS_ABORT dlopen=%s\n", dlerror());return 4;}
    /* Exact20F66 wrappers: s0 float argument/result; setter tail-calls MIG
     * routine returning int32 status. See apple-brightness-abi.json. */
    int32_t (*set)(float) = dlsym(framework, "BKSDisplayBrightnessSetWithImplicitTransaction");
    float (*get)(void) = dlsym(framework, "BKSDisplayBrightnessGetCurrent");
    bool (*available)(void) = dlsym(framework, "BKSDisplayBrightnessIsBrightnessLevelControlAvailable");
    if (!set || !get || !available) {puts("MT6762_BKS_ABORT exports missing");return 5;}
    bool ready = false;
    for (unsigned i = 0; i < 30; i++) {
        ready = available();
        if (ready) break;
        sleep(2);
    }
    printf("MT6762_BKS_READY available=%u native=%d\n", ready, native_level());
    if (!ready) return 6;
    float original = get();
    if (!(original >= 0.0f && original <= 1.0f)) {
        puts("MT6762_BKS_ABORT initial logical brightness invalid");return 7;
    }
    const float targets[3] = {0.25f, 0.75f, original};
    for (unsigned i = 0; i < 3; i++) {
        int32_t status = set(targets[i]);
        printf("MT6762_BKS_REQUEST target=%.6f status=%#x\n", targets[i], status);
        sleep(i < 2 ? hold : 4);
        printf("MT6762_BKS_OBSERVE logical=%.6f native=%d\n", get(), native_level());
        if (status) return 8;
    }
    puts("MT6762_BKS_DONE requests complete; require independent native PWM evidence");
    return 0;
}
