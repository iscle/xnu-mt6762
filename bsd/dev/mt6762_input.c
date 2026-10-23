/* SPDX-License-Identifier: MIT
 * AXS0x3b consumer. The platform owns I2C/clock/pin setup; this driver never
 * resets the controller or uploads its persistent firmware. See the recovered
 * protocol and live-input evidence in tools/mt6762/hardware/display-touch.
 */
#include <kern/clock.h>
#include <kern/thread.h>
#include <mach/mach_types.h>
#include <sys/systm.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_display.h>
#include <sys/redwood_input.h>
#include "../../tools/mt6762/hardware/display-touch/axs_touch_state.h"
extern kern_return_t thread_terminate(thread_t);

static int touch_started;
static uint64_t touch_now_us(void)
{
    uint64_t ns;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    return ns / 1000;
}
static void touch_emit(void *unused, unsigned type, unsigned id, unsigned x, unsigned y)
{
    (void)unused;
    redwood_touch_post(type, id, x, y);
}
static int touch_property(const char *name, uint32_t expected)
{
    uint32_t value;
    return !mt6762_handoff_u32(name, &value) && value == expected;
}
static void touch_worker(void *parameter, wait_result_t result)
{
    struct axs_state state;
    uint8_t version_cmd = 0x0c, version[2], packet[AXS_TOUCH_PACKET_BYTES];
    int error;
    unsigned malformed = 0;
    (void)parameter; (void)result;
    axs_state_init(&state, 384, 854, 100000, touch_emit, NULL);
    error = mt6762_i2c_transfer(0, AXS_TOUCH_ADDRESS, &version_cmd, 1, version, 2);
    if (error || version[0] != 0 || version[1] != 7) {
        printf("mt6762-touch: unavailable: firmware read/identity (error %d); no firmware writes\n", error);
        goto stop;
    }
    printf("mt6762-touch: AXS version0007, bus0 address0x3b, polling8ms; native consumer running\n");
    for (;;) {
        error = mt6762_i2c_transfer(0, AXS_TOUCH_ADDRESS, NULL, 0, packet, sizeof(packet));
        if (error) {
            printf("mt6762-touch: stopped: transport error %d, releasing contacts\n", error);
            break;
        }
        if (axs_state_feed(&state, packet, sizeof(packet), touch_now_us()) < 0) {
            if (++malformed == 8) {
                printf("mt6762-touch: stopped: eight consecutive malformed frames\n");
                break;
            }
        } else {
            malformed = 0;
        }
        /* Expiry also runs on status frames and after the bounded I2C call. */
        delay_for_interval(8000, NSEC_PER_USEC);
        axs_state_expire(&state, touch_now_us());
    }
stop:
    axs_state_release_all(&state);
    thread_terminate(current_thread());
}
void mt6762_touch_init(void)
{
    thread_t thread;
    if (touch_started) return;
    if (!mt6762_platform_ready() || !touch_property("touch-verified", 1) ||
        !touch_property("touch-bus", 0) || !touch_property("touch-address", 0x3b) ||
        !touch_property("touch-max-x", 384) || !touch_property("touch-max-y", 854)) {
        printf("mt6762-touch: unavailable: missing verified handoff\n");
        return;
    }
    if (!mt6762_i2c_ready(0)) {
        printf("mt6762-touch: unavailable: I2C0 prerequisites failed\n");
        return;
    }
    touch_started = 1;
    if (kernel_thread_start(touch_worker, NULL, &thread) != KERN_SUCCESS) {
        printf("mt6762-touch: unavailable: worker allocation failed\n");
        return;
    }
    thread_deallocate(thread);
}
