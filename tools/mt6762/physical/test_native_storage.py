"""Compile the real loader admission against retained phone evidence."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class NativeStorage(unittest.TestCase):
    def test_capture_and_failures(self):
        fixture = json.loads((HERE/'native-storage-fixture.json').read_text())
        pairs = ',\n'.join('{'+a+','+v+'}' for a, v in fixture['registers'].items())
        code = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "native_storage.h"
static const uint32_t words[][2]={PAIRS};
static unsigned calls[sizeof(words)/sizeof(words[0])],msdc_reads;
static uint32_t fault_address,fault_value,change_address;
static uint32_t rd(void *unused,uint32_t address) {
    (void)unused;
    if((address>=0x11230000 && address<0x11231000) ||
       (address>=0x11cd0000 && address<0x11cd1000))msdc_reads++;
    for(unsigned i=0;i<sizeof(words)/sizeof(words[0]);i++)if(words[i][0]==address) {
        calls[i]++;
        if(address==fault_address)return fault_value;
        if(address==change_address && calls[i]>1)return words[i][1]^1;
        return words[i][1];
    }
    fprintf(stderr,"Unaudited fixture read %x\n",address);assert(0);return 0;
}
static void clear(void) {
    memset(calls,0,sizeof(calls));msdc_reads=0;
    fault_address=fault_value=change_address=0;
}
static void rejected(void) {
    struct mt6762_storage_profile out,before;
    memset(&out,0xa5,sizeof(out));before=out;
    assert(!mt6762_storage_profile_read(rd,0,&out));
    assert(!memcmp(&out,&before,sizeof(out)));
}
int main(void) {
    struct mt6762_storage_profile out;
    assert(mt6762_storage_profile_read(rd,0,&out));
    assert(out.sectors==244285440 && out.rca==1 && out.ocr==0xc0ff8080);
    assert(out.card_clock_hz==47999984 && out.hclk_hz==273000000);
    assert(out.pad_drive==0x49240 && out.cfg==0x02200199 && out.sdc_cfg==0x09020000);
    assert(out.top_tune[0]==0x8000 && out.controller_tune[1]==0x403c0007);
    const uint32_t bad[][2]={
        {0x10000070,0x181},{0x10001094,4},{0x100010c8,0x200},
        {0x1000c288,0},{0x1000c27c,0},{0x1000c240,0},
        {0x4804bb18,0},{0x48050e70,0},{0x48146ccc,0},
        {0x48146c50,0},{0x48146d60,0},{0x48146c78,0},
        {0x48146c7c,0},{0x48146c94,0},{0x48146d68,0},
        {0x48146d64,0},{0x48146d64,0x80000000},
        {0x48146d6c,0x80ff8080},{0x48146d78,0},{0x48146d78,0x10000},
        {0x48146d7c,2},{0x48146d80,0x1024d},{0x48146d80,0x2025d},
        {0x0c00010c,0x8000},{0x0c00020c,0x8000},{0x0c00030c,0x8000},
        {0x0c000c18,0x80000000},{0x11230000,0x02200191},
        {0x11230030,0x9010000},{0x1123000c,0x100},{0x11230010,0x100},
        {0x1123003c,1},{0x1123009c,5},{0x11230014,4},
        {0x11230204,1},{0x1123023c,1},{0x11230670,0},
        {0x100053f0,0},{0x10005400,0},{0x10002000,0},
        {0x10002030,0},{0x10002050,0},{0x10002060,0},
        {0x10002090,0x10},{0x10002070,4}};
    for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
        clear();fault_address=bad[i][0];fault_value=bad[i][1];rejected();
        if(i<6)assert(!msdc_reads);
    }
    const uint32_t changed[]={0x1000c280,0x48146d64,0x48146d78,
        0x11230004,0x112300b0,0x11cd0000,0x11cd002c};
    for(unsigned i=0;i<sizeof(changed)/sizeof(changed[0]);i++) {
        clear();change_address=changed[i];rejected();
    }
    assert(!mt6762_storage_profile_read(0,0,&out));
    assert(!mt6762_storage_profile_read(rd,0,0));
    puts("PASS: captured eMMC profile,45 invalid states,7 unstable states; output unchanged on refusal");
}
'''.replace('PAIRS', pairs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'test.c').write_text(code)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O2',
                '-I'+str(HERE),str(root/'test.c'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True)


if __name__ == '__main__':
    unittest.main()
