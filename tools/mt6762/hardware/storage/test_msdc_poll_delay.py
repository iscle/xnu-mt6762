#!/usr/bin/env python3
"""Compile the native delay wrapper with only ARM YIELD/timer operations mocked."""
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]


class PollDelayTest(unittest.TestCase):
    def test_actual_wrapper_uses_counter_without_scheduler_or_wfe(self):
        source = (ROOT / "bsd/dev/mt6762_msdc.c").read_text()
        wrapper = re.search(r"static void delay_us\(void \*unused,uint32_t us\)\n\{.*?\n\}", source, re.S).group()
        # The replacement is intentionally limited to the one non-host opcode.
        wrapper = wrapper.replace('__asm__ volatile("yield" ::: "memory");', 'yield_count++;')
        self.assertNotIn("__asm__", wrapper)
        prefix = r'''
#include <stdint.h>
#include <assert.h>
static uint64_t now,tick_step;
static unsigned yield_count,clock_reads;
#define NSEC_PER_USEC 1000u
static void clock_interval_to_absolutetime_interval(uint32_t us,uint32_t scale,uint64_t *out)
{assert(scale==NSEC_PER_USEC);*out=(uint64_t)us*13;}
static uint64_t mach_absolute_time(void)
{uint64_t result=now;now+=tick_step;clock_reads++;return result;}
'''
        suffix = r'''
int main(void) {
    tick_step=1;delay_us(0,1);
    assert(yield_count==12 && clock_reads==14 && now==14);
    now=clock_reads=yield_count=0;delay_us(0,0);
    assert(!yield_count && clock_reads==2);
    now=clock_reads=yield_count=0;tick_step=10000;delay_us(0,1);
    assert(!yield_count && clock_reads==2); /* preempted past deadline */
    now=UINT64_MAX-5;clock_reads=yield_count=0;tick_step=1;delay_us(0,1);
    assert(yield_count==12 && clock_reads==14); /* modular counter wrap */
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            (path / "wrapper.c").write_text(prefix + wrapper + suffix)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(path / "wrapper.c"), "-o", str(path / "test")], check=True)
            subprocess.run([str(path / "test")], check=True)


if __name__ == "__main__":
    unittest.main()
