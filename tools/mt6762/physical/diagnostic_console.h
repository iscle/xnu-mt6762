/* SPDX-License-Identifier: MIT
 * Tiny original 5x7 diagnostic font. Call only after framebuffer admission.
 */
#ifndef MTK_DIAGNOSTIC_CONSOLE_H
#define MTK_DIAGNOSTIC_CONSOLE_H
#include <stdint.h>
static const uint8_t diagnostic_font[36][7] = {
 {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},
 {30,1,1,14,1,1,30},{2,6,10,18,31,2,2},{31,16,16,30,1,1,30},
 {14,16,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},
 {14,17,17,15,1,1,14},
 {14,17,17,31,17,17,17},{30,17,17,30,17,17,30},{14,17,16,16,16,17,14},
 {30,17,17,17,17,17,30},{31,16,16,30,16,16,31},{31,16,16,30,16,16,16},
 {14,17,16,23,17,17,15},{17,17,17,31,17,17,17},{14,4,4,4,4,4,14},
 {7,2,2,2,2,18,12},{17,18,20,24,20,18,17},{16,16,16,16,16,16,31},
 {17,27,21,21,17,17,17},{17,25,21,19,17,17,17},{14,17,17,17,17,17,14},
 {30,17,17,30,16,16,16},{14,17,17,17,21,18,13},{30,17,17,30,20,18,17},
 {15,16,16,14,1,1,30},{31,4,4,4,4,4,4},{17,17,17,17,17,17,14},
 {17,17,17,17,17,10,4},{17,17,17,21,21,21,10},{17,17,10,4,10,17,17},
 {17,17,10,4,4,4,4},{31,1,2,4,8,16,31}
};
struct diagnostic_console { volatile uint32_t *pixels; unsigned column, row; };
static void diagnostic_character(struct diagnostic_console *c, char ch)
{
    if (!c->pixels) return;
    /* Keep additions bounded even after repeated linefeeds or a bad cursor. */
    if (c->column > 384) c->column = 0;
    if (c->row > 838) c->row = 0;
    if (ch == '\r') {c->column = 0; return;}
    if (ch == '\n') {c->column = 0; c->row = c->row > 822 ? 0 : c->row + 16; return;}
    if (c->column + 12 > 384) {c->column = 0; c->row += 16;}
    if (c->row + 16 > 854) c->row = 0;
    if (ch >= 'a' && ch <= 'z') ch -= 'a'-'A';
    int index = ch >= '0' && ch <= '9' ? ch-'0' : ch >= 'A' && ch <= 'Z' ? ch-'A'+10 : -1;
    for (unsigned y=0; y<16; ++y) for (unsigned x=0; x<12; ++x) {
        unsigned bits = index >= 0 && y < 14 ? diagnostic_font[index][y/2] : 0;
        if (index < 0 && ch != ' ' && ch != '\t' && (y == 6 || y == 7)) bits = 4;
        c->pixels[(c->row+y)*384+c->column+x] = x<10 && (bits & (16u>>(x/2))) ? 0xffffffffu : 0xff001c28u;
    }
    c->column += 12;
}
#endif
