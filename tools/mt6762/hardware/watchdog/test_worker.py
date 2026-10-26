#!/usr/bin/env python3
"""Execute the actual worker/init C against deterministic clocks and MMIO.

Only ARM cache/barrier instructions are removed for this host-only harness.
It does not model watchdog acceptance, IRQ/reset timing or RAM retention.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

here = Path(__file__).resolve().parent
root = here.parents[3]
source = (root / 'bsd/dev/mt6762_platform.c').read_text()
worker = source[source.index('static uintptr_t watchdog;'):source.index('\n#else\nvoid mt6762_platform_init')]
worker, removed = re.subn(r'__asm__ volatile\([^;]+;', '(void)0;', worker)
assert removed == 4, 'review changed ARM cache/barrier sites before updating this harness'
preamble = r'''
#include "trial_deadline.h"
#include <assert.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
typedef void *thread_t;
typedef int wait_result_t;
typedef void *event_t;
#define NSEC_PER_MSEC 1000000
#define THREAD_UNINT 0
#define THREAD_CONTINUE_NULL NULL
#define KERN_SUCCESS 0
static int ready=1;
static uint64_t fake_ns;
static unsigned writes,flushes,blocks,change_after,gap_after;
static const char *arg;
static jmp_buf stop;
static uint32_t r32(uintptr_t base,unsigned offset) {
    assert(base==0x10007000);
    switch(offset) {
    case 0:return change_after&&writes>=change_after ? 0x7c:0x7d;
    case 4:return 0xf000;
    case 0x30:return 0x3f0036;
    case 0x34:return 0x3b0034;
    case 0xc:case 0x20:case 0x24:return 0;
    default:assert(0);return 0;
    }
}
static void w32(uintptr_t base,unsigned offset,uint32_t value) {
    assert(base==0x10007000&&offset==8&&value==0x1971);++writes;
}
static void kprintf(const char *format,...) {(void)format;}
static void clock_get_uptime(uint64_t *now) {*now=fake_ns;}
static void absolutetime_to_nanoseconds(uint64_t ticks,uint64_t *ns) {*ns=ticks;}
static void clock_interval_to_deadline(unsigned n,unsigned unit,uint64_t *out) {
    assert(n==1000&&unit==NSEC_PER_MSEC);*out=fake_ns+1000000000;
}
static void assert_wait_deadline(event_t e,int mode,uint64_t deadline) {
    (void)e;assert(mode==0&&deadline==fake_ns+1000000000);
}
static void thread_block(void *continuation) {
    assert(!continuation);++blocks;
    if(blocks==2000)longjmp(stop,2);
    fake_ns+=gap_after&&writes==gap_after ? UINT64_C(11000000000):UINT64_C(1000000000);
}
static thread_t current_thread(void) {return NULL;}
static void thread_terminate(thread_t t) {(void)t;longjmp(stop,1);}
static int flag(const char *name) {assert(!strcmp(name,"watchdog-refresh-owned"));return 1;}
static void *mt6762_map_mmio(uint64_t base,size_t bytes) {
    assert(base==0x10007000&&bytes==4096);return (void *)(uintptr_t)base;
}
static int PE_parse_boot_arg_str(const char *name,char *out,int capacity) {
    assert(!strcmp(name,"mt6762_trial_seconds"));
    if(!arg)return 0;
    snprintf(out,(size_t)capacity,"%s",arg);return 1;
}
static int kernel_thread_start(void (*fn)(void *,wait_result_t),void *p,thread_t *out) {
    (void)fn;assert(!p);*out=NULL;return 0;
}
static void thread_deallocate(thread_t t) {(void)t;}
static unsigned mt6762_trial_flush_log(uint32_t *before,uint32_t *after) {
    ++flushes;*before=128;*after=129;return MTK_TRIAL_CONCURRENT_LOG;
}
'''
tests = r'''
static void run(const char *argument,unsigned changes,unsigned gap,unsigned expected_writes,int expiry) {
    fake_ns=UINT64_C(7000000000);writes=flushes=blocks=0;
    change_after=changes;gap_after=gap;arg=argument;
    watchdog=0;watchdog_trial_seconds=0;
    memset(&mt6762_trial_record,0,sizeof(mt6762_trial_record));
    mt6762_watchdog_init();
    int stopped=setjmp(stop);
    if(!stopped)watchdog_worker(NULL,0);
    assert(writes==expected_writes);
    assert(flushes==(unsigned)expiry);
    if(expiry) {
        assert(stopped==1&&mt6762_trial_record.state==3);
        assert(mt6762_trial_record.first_feed_ns==UINT64_C(7000000000));
        assert(mt6762_trial_record.last_feed_ns==fake_ns-UINT64_C(1000000000));
        assert(mt6762_trial_record.expired_ns==fake_ns);
        assert(mt6762_trial_record.attempts==expected_writes);
        assert(mt6762_trial_record.mode==0x7d&&mt6762_trial_record.length==0xf000);
        assert(mt6762_trial_record.flags==MTK_TRIAL_CONCURRENT_LOG);
    }
}
int main(void) {
    run(NULL,0,0,2000,0);run("0",0,0,2000,0);
    run("60",0,0,60,1);run("1800",0,0,1800,1);
    run("59",0,0,2000,0);run("1801",0,0,2000,0);
    run("4294967356",0,0,2000,0);run("-60",0,0,2000,0);
    run(NULL,10,0,10,0);run("60",10,0,10,0);
    run(NULL,0,20,20,0);run("60",0,20,20,0);
    puts("PASS:12 actual worker/init executions; exact RESTART-only stores, deadline cessation, unchanged default/failure paths");
}
'''
with tempfile.TemporaryDirectory(prefix='mt6762-trial-') as directory:
    path = Path(directory)
    (path / 'test.c').write_text(preamble + worker + tests)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', '-I', str(here),
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
