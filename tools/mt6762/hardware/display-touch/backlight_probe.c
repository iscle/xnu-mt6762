/* Read-only iOS registry diagnostic. No brightness/PWM/property writes.
 * Build against an iOS SDK with CoreFoundation and IOKit. Run only in the
 * explicitly prepared laboratory userspace; does not connect to a phone. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void property(io_service_t service, CFStringRef key)
{
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key, NULL, 0);
    char name[128] = {0}, description[2048] = {0};
    CFStringGetCString(key, name, sizeof(name), kCFStringEncodingUTF8);
    if (value) {
        CFStringRef text = CFCopyDescription(value);
        if (text) {
            CFStringGetCString(text, description, sizeof(description), kCFStringEncodingUTF8);
            CFRelease(text);
        }
        CFRelease(value);
    }
    printf("MT6762_BL_PROPERTY %s=%s\n", name, value ? description : "<absent>");
}
static void enumerate(const char *label, CFMutableDictionaryRef matching)
{
    io_iterator_t iterator = 0;
    kern_return_t result = IOServiceGetMatchingServices(0, matching, &iterator);
    printf("MT6762_BL_MATCH %s status=%#x\n", label, result);
    if (result) return;
    io_service_t service;
    unsigned count = 0;
    while (count < 16 && (service = IOIteratorNext(iterator))) {
        io_name_t name = {0}, class_name = {0};
        uint64_t registry_id = 0;
        IORegistryEntryGetName(service, name);
        IOObjectGetClass(service, class_name);
        IORegistryEntryGetRegistryEntryID(service, &registry_id);
        printf("MT6762_BL_SERVICE name=%s class=%s id=%llu conforms=%u\n",
            name, class_name, (unsigned long long)registry_id,
            IOObjectConformsTo(service, "AppleARMBacklight"));
        property(service, CFSTR("backlight-control"));
        property(service, CFSTR("IODisplayParameters"));
        property(service, CFSTR("backlight-level"));
        property(service, CFSTR("MT6762BacklightFault"));
        property(service, CFSTR("IOClass"));
        property(service, CFSTR("built-in"));
        IOObjectRelease(service);
        count++;
    }
    IOObjectRelease(iterator);
    printf("MT6762_BL_COUNT %s=%u\n", label, count);
}
int main(int argc, char **argv)
{
    unsigned repeats = argc > 1 ? (unsigned)strtoul(argv[1], NULL, 10) : 1;
    if (!repeats || repeats > 12) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    for (unsigned i = 0; i < repeats; i++) {
        printf("MT6762_BL_PROBE iteration=%u uid=%u readonly=1\n", i, getuid());
        enumerate("AppleARMBacklight", IOServiceMatching("AppleARMBacklight"));
        CFMutableDictionaryRef props = CFDictionaryCreateMutable(NULL, 1,
            &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        CFMutableDictionaryRef matching = CFDictionaryCreateMutable(NULL, 1,
            &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        if (!props || !matching) return 3;
        CFDictionarySetValue(props, CFSTR("backlight-control"), kCFBooleanTrue);
        CFDictionarySetValue(matching, CFSTR("IOPropertyMatch"), props);
        CFRelease(props);
        enumerate("backlight-control=true", matching);
        if (i + 1 < repeats) sleep(10);
    }
    return 0;
}
