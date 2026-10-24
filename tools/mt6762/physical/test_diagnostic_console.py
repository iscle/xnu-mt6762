#!/usr/bin/env python3
"""Exercise the exact diagnostic renderer in guarded host memory, without MMIO."""
from pathlib import Path
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parent
SOURCE=r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "diagnostic_console.h"
int main(void) {
    const size_t count=384U*854U, bytes=count*4U;
    const size_t page=(size_t)sysconf(_SC_PAGESIZE);
    const size_t mapped=(bytes+page-1)&~(page-1);
    unsigned char *area=mmap(0,mapped+2*page,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(area!=MAP_FAILED);
    assert(mprotect(area+page,mapped,PROT_READ|PROT_WRITE)==0);
    /* Tight trailing guard: the first byte after the visible framebuffer faults.
     * The residual prefix is a canary for writes before visible pixel zero. */
    uint32_t *pixels=(uint32_t *)(area+page+mapped-bytes);
    memset(area+page,0xa5,mapped);
    struct diagnostic_console c={pixels,372,838};
    diagnostic_character(&c,'A');
    assert(c.column==384 && c.row==838);
    assert(pixels[count-1]==0xff001c28U);
    diagnostic_character(&c,'B');
    assert(c.column==12 && c.row==0);
    for(size_t n=0;n<(size_t)((unsigned char*)pixels-(area+page));++n) assert(area[page+n]==0xa5);
    c.row=0;c.column=0;
    diagnostic_character(&c,'a');
    uint32_t lower[12*16];
    for(unsigned y=0;y<16;++y) for(unsigned x=0;x<12;++x) lower[y*12+x]=pixels[y*384+x];
    c.column=0;diagnostic_character(&c,'A');
    for(unsigned y=0;y<16;++y) for(unsigned x=0;x<12;++x) assert(lower[y*12+x]==pixels[y*384+x]);
    uint64_t before=0,after=0;
    for(size_t n=0;n<count;++n) before+=pixels[n];
    diagnostic_character(&c,'\r');assert(c.column==0);
    diagnostic_character(&c,'\n');assert(c.column==0 && c.row==16);
    for(size_t n=0;n<count;++n) after+=pixels[n];
    assert(before==after);
    struct diagnostic_console disabled={0,12,32};
    diagnostic_character(&disabled,'A');diagnostic_character(&disabled,'\n');
    assert(disabled.column==12 && disabled.row==32);
    for(unsigned n=0;n<20000;++n) diagnostic_character(&c,n%47==0?'\n':(char)(' '+n%95));
    for(size_t n=0;n<count;++n) assert(pixels[n]==0xa5a5a5a5U || pixels[n]==0xffffffffU || pixels[n]==0xff001c28U);
    for(size_t n=0;n<(size_t)((unsigned char*)pixels-(area+page));++n) assert(area[page+n]==0xa5);
    assert(munmap(area,mapped+2*page)==0);
    return 0;
}
'''
class ConsoleTests(unittest.TestCase):
    def test_exact_renderer_guard_pages_canary_edges_and_wrapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary); source=directory/'test.c'; binary=directory/'test'
            source.write_text(SOURCE)
            subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=10)
if __name__=='__main__':unittest.main()
