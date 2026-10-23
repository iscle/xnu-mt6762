/* Synthetic protocol vectors, not captured physical touch packets. */
#include "axs_touch.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>

int main(void)
{
    uint8_t p[32] = {0, 2, 0x01, 0x7f, 0x03, 0x55, 0x20, 0x90,
                          0x80, 0x01, 0x40, 0x02, 0x00, 0x00};
    struct axs_frame f;
    assert(axs_touch_decode(p, sizeof p, &f) == 1);
    assert(f.count == 2 && f.active_mask == 0x11);
    assert(f.contacts[0].x == 383 && f.contacts[0].y == 853);
    assert(f.contacts[0].pressure == 32 && f.contacts[0].area == 9);
    assert(f.contacts[1].id == 4 && f.contacts[1].event == 2);
    assert(f.contacts[1].pressure == 63 && f.contacts[1].area == 9);
    p[2] = 0x41; /* up: still decode position but no active contact bit */
    assert(axs_touch_decode(p, sizeof p, &f) == 1 && f.active_mask == 0x10);
    p[10] = 0x50; /* invalid contact id terminates records */
    assert(axs_touch_decode(p, sizeof p, &f) == 1 && f.count == 1);
    p[1] = 0;
    assert(axs_touch_decode(p, sizeof p, &f) == 1 && f.count == 0 && !f.active_mask);
    p[1] = 0x10;
    f.count = 77;
    assert(axs_touch_decode(p, sizeof p, &f) == -1 && f.count == 77);
    p[0] = 0xff;
    assert(axs_touch_decode(p, sizeof p, &f) == 0 && f.count == 77);
    assert(axs_touch_decode(p, 31, &f) == -1);
    assert(axs_touch_decode(NULL, 32, &f) == -1);
    memset(p, 0, sizeof p); p[1] = 15;
    assert(axs_touch_decode(p, sizeof p, &f) == 1 && f.count == 5);
    puts("AXS synthetic parser vectors passed");
}
