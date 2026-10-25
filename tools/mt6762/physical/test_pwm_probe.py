#!/usr/bin/env python3
"""Run actual passive-probe C through clock/power failure paths and decode it."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import pwm_record as record

HERE=Path(__file__).resolve().parent
SOURCE=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "pwm_probe.h"
static const uint64_t addresses[] = {
 0x10006180,0x10006184,0x1000630c,0x10000080,0x100010ac,0x10005350,
 0x10006458,0x1100e000,0x1100e00c,0x1100e018,0x1100e01c,0x1100e080};
static const uint32_t values[] = {8,8,13,0,0,0x1000,5,1,0,0,0x01ff03ff,0};
struct fixture {unsigned parent,reads,fail_at,fail_value;};
static uint32_t read_reg(void *context,uint64_t address) {
 struct fixture *f=context; ++f->reads;
 for (unsigned i=0;i<12;++i) if(address==addresses[i]) {
  if(f->reads==f->fail_at) return f->fail_value;
  if(i==3) return f->parent<<24;
  return values[i];
 }
 assert(!"read outside PWM allowlist");return 0;
}
static void barrier(void *context) {(void)context;}
static struct pwm_probe_record run(struct fixture *f,unsigned state,unsigned reads) {
 struct pwm_probe_record r={0};struct display_probe_io io={f,read_reg,barrier};
 pwm_probe_capture(&io,&r);
 assert(r.state==state && r.state_inverse==~state && f->reads==reads);
 return r;
}
int main(int argc,char **argv) {
 assert(argc==2);struct fixture f={0};struct pwm_probe_record r;
 for (unsigned parent=0;parent<4;++parent) {
  unsigned step=parent>=2?12:11;
  f=(struct fixture){.parent=parent};r=run(&f,PWM_COMPLETE,2*step);
  assert(r.pass==2 && r.snapshots[0].mask==(parent>=2?31u:23u));
  assert(!memcmp(&r.snapshots[0],&r.snapshots[1],sizeof(r.snapshots[0])));
  for(unsigned pass=0;pass<2;++pass) {
   for(unsigned i=1;i<=5;++i) {
    unsigned bad=i==4?0x80000000u:i==5?4:0;
    f=(struct fixture){.parent=parent,.fail_at=pass*step+i,.fail_value=bad};
    r=run(&f,PWM_UNAVAILABLE,pass*step+6);
    assert(r.pass==pass+1 && r.snapshots[pass].mask==7);
   }
   if(parent>=2) {
    for(unsigned bad=0;bad<5;++bad) {
     f=(struct fixture){.parent=parent,.fail_at=pass*step+7,.fail_value=bad};
     r=run(&f,PWM_UNAVAILABLE,pass*step+7);
     assert(r.snapshots[pass].mask==15);
    }
   }
  }
 }
 f=(struct fixture){0};r=run(&f,PWM_COMPLETE,22);
 memcpy(r.magic,"MTKPWM01",8);r.version=1;r.size=sizeof(r);
 for(unsigned i=0;i<32;++i)r.identity[i]=i;
 FILE *out=fopen(argv[1],"wb");assert(out && fwrite(&r,sizeof(r),1,out)==1);assert(!fclose(out));
 return 0;
}
'''


class PWMTests(unittest.TestCase):
    def test_production_probe_and_wire(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(SOURCE)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test'),str(p/'record')],check=True,timeout=10)
            raw=(p/'record').read_bytes();decoded=record.decode(raw,bytes(range(32)))
            self.assertTrue(decoded['stable_complete'])
            self.assertFalse(decoded['native_ownership'])
            self.assertEqual(decoded['snapshots'][0]['parent_selector'],0)
            self.assertEqual(decoded['snapshots'][0]['divider'],0)
            self.assertEqual(decoded['snapshots'][0]['gpio43_mode'],1)
            self.assertEqual(decoded['snapshots'][0]['duty'],511)
            changed=bytearray(raw);struct.pack_into('<I',changed,128+11*4,0x010003ff)
            self.assertFalse(record.decode(changed,bytes(range(32)))['stable_complete'])

    def test_stale_torn_and_partial_records(self):
        identity=bytes(range(32));raw=record.initialized(identity)
        self.assertEqual(record.decode(raw,identity)['state'],0)
        with self.assertRaises(ValueError):record.decode(raw,identity[::-1])
        for offset in (0,8,12,48,52,56,60,64,116,180,192,255):
            changed=bytearray(raw);changed[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError):
                record.decode(changed,identity)
        changed=bytearray(raw);struct.pack_into('<4I',changed,48,1,0xfffffffe,1,0)
        # A fault during a group exposes only the already completed groups.
        struct.pack_into('<4I',changed,64,1,8,8,13)
        struct.pack_into('<I',changed,80,0x1234)
        decoded=record.decode(changed,identity)
        self.assertNotIn('top',decoded['snapshots'][0])
        self.assertFalse(decoded['stable_complete'])


if __name__=='__main__':unittest.main()
