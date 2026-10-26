#!/usr/bin/env python3
"""Host tests use synthetic bytes only; no original firmware/calibration committed."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import os
import tempfile
import unittest
import validate as v

class Connectivity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mtk-conn-test-')
        cls.lib = v.compile_core(cls.temp.name)
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
    def image(self, data, kind):
        return v.structural(self.lib, bytes(data), kind)
    def wlan(self):
        region = struct.pack('<6IB15s', 0, 0, 0, 0, 0x2000, 16, 7, bytes(15))
        tail = bytes([7, 0, 1, 2, 0, 0, 0]) + b'tk__000200' + b'20231228121053\0' + bytes(4)
        return bytearray(bytes(16) + region + tail)
    def ram(self):
        return bytearray(b'2312281205560000ALPS' + bytes.fromhex('8a008a00') + struct.pack('<II', 0xf0000011, 0x4000000) + bytes(16) + bytes(32))
    def calibration(self):
        # Synthetic locally administered unicast address; never a physical fixture.
        return bytearray(struct.pack('<HH', 1, 8) + b'\x02\x00\x00\x00\x00\x01' + bytes(2040))
    def test_positive_regions(self):
        r = self.image(self.wlan(), 1)
        self.assertEqual(r['payload_bytes'], 16)
        self.assertEqual(r['regions'][0]['device_address'], 0x2000)
    def test_all_truncated_prefixes(self):
        for kind, b in [(1,self.wlan()), (3,self.ram()), (4,self.calibration())]:
            limit = 76 if kind == 1 else 49 if kind == 3 else 2050
            for n in range(limit):
                with self.assertRaises(ValueError, msg=f'{kind}/{n}'):
                    self.image(b[:n],kind)
    def test_count_overflow(self):
        for count in [0, 2, 17, 255]:
            b=self.wlan();b[-34]=count
            with self.assertRaises(ValueError): self.image(b,1)
    def test_region_length_and_address_overflow(self):
        for at,value in [(36,0),(36,17),(32,0xffffffff)]:
            b=self.wlan();struct.pack_into('<I',b,at,value)
            with self.assertRaises(ValueError): self.image(b,1)
    def test_unsupported_compression_feature_format(self):
        for at in [16,40,-33,-31]:
            b=self.wlan();b[at]=99
            with self.assertRaises(ValueError): self.image(b,1)
    def test_overlapping_regions(self):
        b=self.wlan();b=b[:16]*2+b[16:56]*2+b[-36:];b[-34]=2
        with self.assertRaises(ValueError):self.image(b,1)
    def test_release_info_bounds(self):
        b=self.wlan();b[-32]=1
        gap=b'################'+struct.pack('<HBB',5,0,0)+struct.pack('<HBB',1,0,1)+b'x'+b'################'
        b=b[:16]+gap+b[16:]
        self.image(b,1)
        b[16+20]=255
        with self.assertRaises(ValueError):self.image(b,1)
    def test_ram_header(self):
        self.assertEqual(self.image(self.ram(),3)['image_type'],0x4000000)
        for at in [0,16,31]:
            b=self.ram();b[at]=0xff
            with self.assertRaises(ValueError):self.image(b,3)
    def test_patch_header(self):
        b=self.ram()[:28]+bytes(16)
        self.image(b,2)
        with self.assertRaises(ValueError):self.image(b[:28],2)
    def test_calibration_boundaries(self):
        self.image(self.calibration(),4)
        for at,val in [(0,2),(2,9),(4,1)]:
            b=self.calibration();b[at]=val
            with self.assertRaises(ValueError):self.image(b,4)
        b=self.calibration();b[4:10]=bytes(6)
        with self.assertRaises(ValueError):self.image(b,4)
        with self.assertRaises(ValueError):self.image(self.calibration()+b'x',4)
    def test_hash_mismatch_even_valid_structure(self):
        path=Path(self.temp.name)/'synthetic-calibration'
        b=self.calibration();path.write_bytes(b)
        expected={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'kind':4}
        v.checked_file(self.lib,path,expected)
        b[100]=1;path.write_bytes(b)
        with self.assertRaisesRegex(ValueError,'sha256'):v.checked_file(self.lib,path,expected)
        path.write_bytes(b[:-1])
        with self.assertRaisesRegex(ValueError,'size'):v.checked_file(self.lib,path,expected)
    def test_failed_parse_keeps_output(self):
        out=v.Image();C.memset(C.byref(out),0xa5,C.sizeof(out));before=bytes(out)
        self.assertNotEqual(self.lib.conn_image_parse(b'',0,1,C.byref(out)),0)
        self.assertEqual(bytes(out),before)
    def entries(self):
        return [(self.lib.conn_register_address(i),x,x,4,3) for i,x in enumerate([2,2,13,0,0,0,0,0,0])]
    def state(self, entries=None, enabled=True, **kwargs):
        return v.decode_record(self.lib,v.make_record(self.entries() if entries is None else entries,**kwargs),enabled)
    def test_state_default_off_and_ready_not_ownership(self):
        raw=v.make_record(self.entries())
        self.assertEqual(v.decode_record(self.lib,raw)['power_interpretation'],'unknown')
        r=self.state();self.assertEqual(r['power_interpretation'],'power-bits-ready-only')
        self.assertFalse(r['conn_mmio_authorized']);self.assertFalse(r['dma_authorized'])
    def test_state_off_and_inconsistent(self):
        e=self.entries();e[0]=(e[0][0],0,0,4,3);e[1]=(e[1][0],0,0,4,3)
        self.assertEqual(self.state(e)['power_interpretation'],'off')
        e[1]=(e[1][0],2,2,4,3)
        self.assertEqual(self.state(e)['power_interpretation'],'transition')
    def test_state_unstable_missing_isolation(self):
        e=self.entries();e[0]=(e[0][0],0,2,4,3)
        self.assertEqual(self.state(e)['power_interpretation'],'unknown')
        self.assertNotEqual(self.state(e)['missing'],0)
        e=self.entries();e[3]=(e[3][0],0x6000,0x6000,4,3)
        self.assertEqual(self.state(e)['power_interpretation'],'isolated')
    def test_state_rejects_unknown_duplicate_width_and_flags(self):
        for e in [[(0x18000000,0,0,4,3)],self.entries()[:1]*2,[(0x10006180,0,0,2,3)],[(0x10006180,0,0,4,4)]]:
            with self.assertRaises(ValueError):self.state(e)
    def test_record_bounds_and_time(self):
        raw=v.make_record(self.entries())
        for cut in [0,47,len(raw)-1]:
            with self.assertRaises(ValueError):v.decode_record(self.lib,raw[:cut],True)
        for kwargs in [{'begin':2,'end':1},{'hz':0},{'end':11,'hz':1}]:
            with self.assertRaises(ValueError):self.state(**kwargs)
        b=bytearray(raw);b[20]=1
        with self.assertRaises(ValueError):v.decode_record(self.lib,bytes(b),True)
    def test_profile_no_private_addresses_or_payload(self):
        p=json.loads((v.HERE/'stock-profile.json').read_text())
        for item in list(p['files'].values())+[p['calibration']]:
            self.assertEqual(set(item),{'bytes','sha256','kind'})
            self.assertEqual(len(item['sha256']),64)
    def test_guard_page_truncated_inputs(self):
        # Real inaccessible tail, independent of Python's oversized bytes storage.
        source = Path(self.temp.name) / 'guard.c'
        binary = Path(self.temp.name) / 'guard'
        source.write_text(r'''#define _GNU_SOURCE
#include <sys/mman.h>
#include <unistd.h>
#include <string.h>
#include "conn_decode.h"
int main(void) {
 size_t page=(size_t)sysconf(_SC_PAGESIZE), n; unsigned kind;
 unsigned char *p=mmap(0,page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 struct conn_image image;struct conn_state state;
 if(p==MAP_FAILED||mprotect(p+page,page,PROT_NONE)) return 2;
 memset(p,0,page);
 for(n=0;n<2050;n++) for(kind=1;kind<=4;kind++) {
  if(conn_image_parse(p+page-n,n,kind,&image)==0) return 3;
 }
 for(n=0;n<48;n++) if(conn_state_parse(p+page-n,n,0,&state)==0) return 4;
 munmap(p,page*2);return 0;
}
''')
        subprocess.run([os.environ.get('CC','cc'),'-std=c99','-Wall','-Wextra','-Werror',
                        '-I',str(v.HERE),str(source),str(v.HERE/'conn_decode.c'),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True)

    def test_display_external_binding(self):
        # Minimal completed v2 display fixture; only power bits used by this tool.
        b=bytearray(512);b[:8]=b'MTKDSP01';struct.pack_into('<II',b,8,2,512);b[16:48]=bytes(range(32))
        struct.pack_into('<4I',b,48,8,2,63,0xfffffff7);struct.pack_into('<3I',b,88,0x434c,0x434c,0xe0d);struct.pack_into('<I',b,104,1)
        path=Path(self.temp.name)/'display';path.write_bytes(b)
        self.assertEqual(v.display_observations(path,bytes(range(32)))['power_interpretation'],'off-at-recorded-sample')
        with self.assertRaises(ValueError):v.display_observations(path,bytes(32))
        b[60]^=1;path.write_bytes(b)
        with self.assertRaises(ValueError):v.display_observations(path,bytes(range(32)))

if __name__=='__main__':unittest.main()
