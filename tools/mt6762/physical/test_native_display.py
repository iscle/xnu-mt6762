#!/usr/bin/env python3
"""Reject mismatched or incomplete physical ownership records before ADT grants."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
SOURCE=r'''
#include <assert.h>
#include "native_display.h"
int main(void) {
 struct display_probe_record d={.state=DISPLAY_ACCEPTED,.state_inverse=~(uint32_t)DISPLAY_ACCEPTED,
  .pass=2,.read_mask=63,.sources=3,.layer=1,.tag_base=0x7ef90000,.tag_size=0x470000,.datapath=0x81000001};
 struct pwm_probe_record p={.state=PWM_COMPLETE,.state_inverse=~(uint32_t)PWM_COMPLETE,.pass=2};
 for(unsigned i=0;i<2;++i)p.snapshots[i]=(struct pwm_probe_snapshot){
  .mask=23,.power={0x434c,0x434c,0xe0d},.top=0x30101,.gpio=0x11111441,.enable=1,.con1=0x03ff03ff};
 assert(native_display_admitted(0x7f0d4000,&d,&p));
 assert(!native_display_admitted(0x7ef90000,&d,&p));
 struct display_probe_record bad;
 bad=d;bad.state=DISPLAY_READING;assert(!native_display_admitted(0x7f0d4000,&bad,&p));
 bad=d;bad.state_inverse=0;assert(!native_display_admitted(0x7f0d4000,&bad,&p));
 bad=d;bad.sources=2;assert(!native_display_admitted(0x7f0d4000,&bad,&p));
 bad=d;bad.tag_size=0x144000;assert(!native_display_admitted(0x7f0d4000,&bad,&p));
 bad=d;bad.identity[0]=1;assert(!native_display_admitted(0x7f0d4000,&bad,&p));
 bad=d;bad.datapath=1;assert(!native_display_admitted(0x7f0d4000,&bad,&p));
 for(unsigned i=0;i<2;++i) {
  struct pwm_probe_record q=p;q.snapshots[i].mask=7;assert(!native_display_admitted(0x7f0d4000,&d,&q));
  q=p;q.snapshots[i].power[1]=0;assert(!native_display_admitted(0x7f0d4000,&d,&q));
  q=p;q.snapshots[i].top=3u<<24;assert(!native_display_admitted(0x7f0d4000,&d,&q));
  q=p;q.snapshots[i].gpio=0;assert(!native_display_admitted(0x7f0d4000,&d,&q));
  q=p;q.snapshots[i].con1=0x010003ff;assert(!native_display_admitted(0x7f0d4000,&d,&q));
 }
 return 0;
}
'''

class NativeDisplayTests(unittest.TestCase):
    def test_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(SOURCE)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True,timeout=10)

if __name__=='__main__':unittest.main()
