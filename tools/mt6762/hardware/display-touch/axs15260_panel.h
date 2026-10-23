/* SPDX-License-Identifier: MIT
 * Panel command sequence reconstructed from this phone's stock kernel.
 * Stock init table VA 0xffffff800983e9f8; push_table 0xffffff8008747b30.
 * The caller must establish and validate MT6762 DSI, clocks, pins and power.
 * This file does not itself establish a working scanout path.
 */
#ifndef MT6762_AXS15260_PANEL_H
#define MT6762_AXS15260_PANEL_H
#include <stddef.h>
#include <stdint.h>
struct axs15260_command {
    uint16_t command; /* 0xffe means millisecond delay */
    uint8_t count;
    uint8_t data[11];
};
static const struct axs15260_command axs15260_init_commands[] = {
    {0xbb,8,{0,0,0,0,0,0,0x5a,0xa5}},
    {0xb2,11,{0x01,0,0,0x06,0,0x0a,0x04,0x21,0x9c,0,0x1e}},
    {0xb2,1,{0x41}},
    {0x11,1,{0}}, {0xffe,120,{0}},
    {0x29,1,{0}}, {0xffe,10,{0}},
};
static const struct axs15260_command axs15260_suspend_commands[] = {
    {0x28,1,{0}}, {0xffe,120,{0}},
    {0x10,1,{0}}, {0xffe,30,{0}},
};
/* Stock selects this branch only for the proximity-preserved power state. */
static const struct axs15260_command axs15260_proximity_resume_commands[] = {
    {0x11,1,{0}}, {0xffe,150,{0}},
    {0x29,1,{0}}, {0xffe,20,{0}},
};
struct axs15260_transport {
    void *context;
    int (*dcs_write)(void *, uint8_t, const uint8_t *, size_t);
    void (*delay_ms)(void *, unsigned);
};
static inline int axs15260_send_sequence(const struct axs15260_transport *io,
    const struct axs15260_command *commands, size_t count)
{
    if (!io || !io->dcs_write || !io->delay_ms || !commands) return -1;
    for (size_t i = 0; i < count; ++i) {
        const struct axs15260_command *c = &commands[i];
        if (c->command == 0xffe) io->delay_ms(io->context, c->count);
        else {
            if (c->command > 255 || c->count > sizeof c->data) return -1;
            int result = io->dcs_write(io->context, (uint8_t)c->command, c->data, c->count);
            if (result) return result;
        }
    }
    return 0;
}
#endif
