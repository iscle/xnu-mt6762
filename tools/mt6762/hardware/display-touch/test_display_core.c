/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdio.h>
#include "mt6762_display_core.h"
struct mock_pwm {
    uint32_t registers[8];
    unsigned count, barriers, offsets[4], drop_writes;
    uint32_t values[4];
};
static uint32_t mock_read(void *context, unsigned offset)
{ return ((struct mock_pwm *)context)->registers[offset / 4]; }
static void mock_write(void *context, unsigned offset, uint32_t value)
{
    struct mock_pwm *p = context;
    assert(p->count < 4 && p->barriers == p->count);
    p->offsets[p->count] = offset; p->values[p->count++] = value;
    if (!p->drop_writes) p->registers[offset / 4] = value;
}
static void mock_barrier(void *context) { ++((struct mock_pwm *)context)->barriers; }
int main(void)
{
    struct mt6762_fb_layout f = {0x7ef90000, 0x470000, 0x7ef90000, 0x470000, 384, 854, 1536, 1, 0};
    assert(mt6762_fb_bounds(&f));
    struct mt6762_fb_layout bad = f;
    bad.size = 1024; assert(!mt6762_fb_bounds(&bad));
    bad = f; bad.physical++; assert(!mt6762_fb_bounds(&bad));
    bad = f; bad.reserved_base++; assert(!mt6762_fb_bounds(&bad));
    bad = f; bad.reserved_size--; assert(!mt6762_fb_bounds(&bad));
    bad = f; bad.physical = 0xffff0000; bad.reserved_base = bad.physical;
    assert(!mt6762_fb_bounds(&bad));
    bad = f; bad.format = 2; assert(!mt6762_fb_bounds(&bad));
    bad = f; bad.stride = UINT32_MAX; assert(!mt6762_fb_bounds(&bad));
    assert(mt6762_display_power(8, 8, 13));
    assert(!mt6762_display_power(8, 0, 13));
    assert(!mt6762_display_power(8, 8, 13 | 0x1000));
    assert(!mt6762_display_power(8, 8, 13 | 0x10));
    struct mt6762_ovl_snapshot s = {
        .en=1, .sources=1, .roi=384 | 854u<<16, .con=0x20ff,
        .address=0x7ef90000, .pitch=1536, .size=384 | 854u<<16,
        .rdma=1, .downstream_rdma=1, .dsi_start=1, .dsi_mode=2,
        .dsi_lanes=7u<<2, .dsi_active=854, .dsi_ps=(3u<<16)|1152,
        .dsi_vsa=2, .dsi_vbp=20, .dsi_vfp=170
    };
    assert(mt6762_ovl_matches(&f, &s));
    s.con |= 0x100; assert(mt6762_ovl_matches(&f, &s));
    s.con--; assert(!mt6762_ovl_matches(&f, &s)); s.con=0x20ff;
    s.con |= 1u<<24; assert(!mt6762_ovl_matches(&f, &s)); s.con=0x20ff;
    s.sources=3; assert(!mt6762_ovl_matches(&f, &s)); s.sources=1;
    s.ext_sources=1; assert(!mt6762_ovl_matches(&f, &s)); s.ext_sources=0;
    s.address+=4096; assert(!mt6762_ovl_matches(&f, &s)); s.address-=4096;
    s.downstream_rdma=3; assert(!mt6762_ovl_matches(&f, &s)); s.downstream_rdma=1;
    s.dsi_ps=(2u<<16)|1152; assert(!mt6762_ovl_matches(&f,&s));
    s.dsi_ps=(3u<<16)|1152;
    s.pitch|=1u<<16; assert(!mt6762_ovl_matches(&f,&s)); s.pitch=1536;
    struct mt6762_ovl_snapshot menu[2]={s,s};
    menu[0].sources=menu[1].sources=3; menu[0].con=menu[1].con=0x21ff;
    menu[1].address+=0x144000;
    assert(mt6762_boot_menu_buffer(f.physical,f.reserved_size,menu)==0x7f0d4000);
    assert(!mt6762_boot_menu_buffer(f.physical,0x144000,menu));
    menu[1].address+=0x4000; assert(!mt6762_boot_menu_buffer(f.physical,f.reserved_size,menu));
    menu[1].address-=0x4000;
    menu[0].sources=7; assert(!mt6762_boot_menu_buffer(f.physical,f.reserved_size,menu));
    s.dsi_lanes=3u<<2; assert(!mt6762_ovl_matches(&f, &s));
    assert(mt6762_pwm_configured(3u<<16, 1023, 3u<<24, 0));
    assert(!mt6762_pwm_configured(3u<<16, 1023, 0, 0));
    assert(!mt6762_pwm_configured(3u<<16, 1023, 3u<<24, 4));
    assert(!mt6762_pwm_configured(3u<<16, 1023, 0x83000000, 0));
    struct mock_pwm p = {.registers = {0x80,0,0,0,0,0,3u<<16,0xa00003ff}};
    const struct mt6762_pwm_io io = {&p, mock_read, mock_write, mock_barrier};
    assert(mt6762_pwm_program(&io, 1024) < 0 && !p.count);
    assert(!mt6762_pwm_program(&io, 700) && p.count == 4 && p.barriers == 4);
    assert(p.offsets[0]==0x1c && p.values[0]==(0xa00003ffu | 700u<<16));
    assert(p.offsets[1]==0 && p.values[1]==0x81);
    assert(p.offsets[2]==0x0c && p.values[2]==1 && p.offsets[3]==0x0c && p.values[3]==0);
    p.count=p.barriers=0;
    assert(!mt6762_pwm_program(&io, 0));
    assert(p.values[0]==0xa00103ff && p.values[1]==0x80);
    p.count=p.barriers=0; p.registers[7]=1022;
    assert(mt6762_pwm_program(&io, 1)<0 && !p.count && !p.barriers);
    p.registers[7]=1023; p.drop_writes=1;
    assert(mt6762_pwm_program(&io, 50)<0 && p.count==4 && p.barriers==4);
    puts("display bounds/readback and PWM ordering tests passed");
    return 0;
}
