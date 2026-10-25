#!/usr/bin/env python3
"""Exercise the actual loader validator: no reads past failed power/gates."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import display_record as record

HERE = Path(__file__).resolve().parent
SOURCE = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "display_probe.h"
static const uint64_t addresses[] = {
 0x10006180,0x10006184,0x1000630c,0x14000100,0x1400b02c,
 0x1400b00c,0x1400b324,0x1400b020,0x1400b030,0x1400bf40,0x1400b044,
 0x1400b038,0x1400b03c,0x1400b04c,0x1400b0c0,0x1400d010,0x14014000,
 0x14014014,0x14014018,0x1401402c,0x1401401c,0x14014020,0x14014024,0x14014028};
static uint32_t values[] = {8,8,13,0,1,1,0,384|(854<<16),0x21ff,0x7ef90000,
 1536,384|(854<<16),0,0,1,1,1,2,7<<2,854,(3<<16)|1152,2,20,170};
struct fixture {unsigned reads, barriers, fail_read, fail_value, sources;};
static uint32_t read_reg(void *context,uint64_t address) {
 struct fixture *f=context; ++f->reads;
 if(address==0x1400b024 || address==0x1400b3a0) return f->reads==f->fail_read?f->fail_value:0;
 for(unsigned n=0;n<sizeof(addresses)/sizeof(addresses[0]);++n) {
  int matches=addresses[n]==address;
  /* Per-layer OVL registers are readable only for enabled sources. */
  if(n>=8 && n<=14) for(unsigned l=1;l<4;++l)
   if((f->sources&(1u<<l)) && address==addresses[n]+l*0x20) matches=1;
  if(!matches) continue;
  if(f->reads==f->fail_read) return f->fail_value;
  if(n==4) return f->sources;
  if(n==9 && f->sources==3 && address==0x1400bf60) return values[n]+0x144000;
  return values[n];
 }
 assert(!"unapproved register read");return 0;
}
static void barrier(void *context) {((struct fixture*)context)->barriers++;}
static struct display_probe_record run(struct fixture *f,struct mtk_fdt_framebuffer tag,
 int reserved,unsigned state,unsigned reads) {
 struct display_probe_record r={0};struct display_probe_io io={f,read_reg,barrier};
 uint64_t result=display_probe_console(&tag,reserved,&io,&r);
 assert(result==(state==DISPLAY_ACCEPTED?tag.base+(f->sources==3?0x144000:0):0));
 assert(r.state==state && r.state_inverse==~state && f->reads==reads);
 assert(f->barriers==4);return r;
}
int main(int argc,char **argv) {
 assert(argc==2);
 struct mtk_fdt_framebuffer tag={.base=0x7ef90000,.size=0x470000,.present=16,.found=1};
 struct fixture f={.sources=1};struct display_probe_record r=run(&f,tag,1,DISPLAY_ACCEPTED,52);
 assert(r.pass==2 && r.read_mask==63 && r.scanout[0].address==tag.base);
 struct mtk_fdt_framebuffer bad=tag;bad.found=0;
 f=(struct fixture){.sources=1};run(&f,bad,1,DISPLAY_TAG,0);
 bad=tag;bad.base++;f=(struct fixture){.sources=1};run(&f,bad,1,DISPLAY_BOUNDS,0);
 f=(struct fixture){.sources=1};run(&f,tag,0,DISPLAY_RESERVATION,0);
 for(unsigned pass=0;pass<2;++pass) {
  for(unsigned n=1;n<=3;++n) {
   f=(struct fixture){.sources=1,.fail_read=pass*26+n,.fail_value=0};
   r=run(&f,tag,1,DISPLAY_POWER,pass*26+3);assert(r.pass==pass+1 && r.read_mask==3);
  }
  f=(struct fixture){.sources=1,.fail_read=pass*26+4,.fail_value=1<<7};
  r=run(&f,tag,1,DISPLAY_GATES,pass*26+4);assert(r.pass==pass+1 && r.read_mask==7);
  f=(struct fixture){.sources=1,.fail_read=pass*26+5,.fail_value=0};
  r=run(&f,tag,1,DISPLAY_SOURCES,pass*26+5);assert(r.read_mask==15);
  f=(struct fixture){.sources=1,.fail_read=pass*26+10,.fail_value=0x7f218000};
  r=run(&f,tag,1,DISPLAY_SCANOUT,pass*26+26);
  assert(r.scanout[0].address==0x7f218000 && r.pass==pass+1);
 }
 f=(struct fixture){.sources=3};r=run(&f,tag,1,DISPLAY_ACCEPTED,90);
 assert(r.read_mask==63 && r.scanout[0].sources==3 && r.scanout[1].sources==3);
 f=(struct fixture){.sources=15};r=run(&f,tag,1,DISPLAY_SOURCES,83);
 for(unsigned i=0;i<4;++i) assert(r.scanout[i].address==tag.base);
 f=(struct fixture){.sources=16};run(&f,tag,1,DISPLAY_SOURCES,5);
 for(unsigned pass=0;pass<2;++pass) for(unsigned n=25;n<=26;++n) {
  f=(struct fixture){.sources=1,.fail_read=pass*26+n,.fail_value=1u<<9};
  r=run(&f,tag,1,DISPLAY_DATAPATH,pass*26+26);assert(r.read_mask==63);
 }
 for(unsigned i=0;i<4;++i) {
  f=(struct fixture){.sources=1u<<i};r=run(&f,tag,1,DISPLAY_ACCEPTED,52);
  assert(r.layer==i && r.scanout[i].sources==(1u<<i));
 }
 memcpy(r.magic,"MTKDSP01",8);r.version=2;r.size=sizeof(r);
 for(unsigned i=0;i<32;++i) r.identity[i]=i;
 FILE *out=fopen(argv[1],"wb");assert(out && fwrite(&r,sizeof(r),1,out)==1);assert(!fclose(out));
 return 0;
}
'''


class DisplayTests(unittest.TestCase):
    def test_actual_mmio_sequence_and_wire_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'test.c').write_text(SOURCE)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                            '-I'+str(HERE),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test'),str(p/'record')],check=True,timeout=10)
            decoded = record.decode((p/'record').read_bytes(), bytes(range(32)))
            self.assertTrue(decoded['accepted'])
            self.assertEqual(decoded['scanout']['3']['address'], 0x7ef90000)
            self.assertEqual(list(decoded['scanout']), ['3'])
            self.assertFalse(decoded['native_ownership'])

    def test_unexecuted_torn_stale_and_mask_validation(self):
        identity = bytes(range(32))
        raw = record.initialized(identity)
        self.assertEqual(record.decode(raw,identity)['state'],0)
        with self.assertRaises(ValueError): record.decode(raw,identity[::-1])
        for offset in (0,8,12,48,52,56,60,440,511):
            changed = bytearray(raw); changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                record.decode(changed,identity)
        for mask in (0,3,15,31):
            changed=bytearray(raw);struct.pack_into('<4I',changed,48,8,2,mask,0xfffffff7)
            with self.assertRaises(ValueError): record.decode(changed,identity)


if __name__ == '__main__': unittest.main()
