#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import struct
import unittest
import decode_trial as d


def record(state=3):
    raw = bytearray(128)
    struct.pack_into('<QII', raw, 0, d.MAGIC, 1, state)
    if state:
        struct.pack_into('<I', raw, 16, 60)
        struct.pack_into('<Q', raw, 32, 7*10**9)
    if state >= 2:
        struct.pack_into('<II', raw, 20, 60, 1)
        struct.pack_into('<QQ', raw, 40, 66*10**9, 67*10**9)
        struct.pack_into('<7I', raw, 64, 0x7d, 0xf000, 0, 0, 0, 0x3f0036, 0x3b0034)
    return raw


def macho(symbol=True):
    va = 0xfffffff007b20000
    section = struct.pack('<16s16sQQ8I',b'__data',b'__DATA',va,0x3000,0,6,0,0,0,0,0,0)
    commands = [struct.pack('<II16s4Q4I', 0x19, 152, b'__DATA', va, 0x4000, 0, 0x3000, 3, 3, 1, 0)+section]
    if symbol:
        commands += [struct.pack('<6I', 2, 24, 0x800, 2, 0x900, 64)]
    raw = bytearray(12288)
    struct.pack_into('<8I', raw, 0, 0xfeedfacf, 0x100000c, 0, 2, len(commands), sum(map(len, commands)), 0, 0)
    raw[32:32+sum(map(len, commands))] = b''.join(commands)
    if symbol:
        # Actual unstripped XNU includes an N_GSYM debug record as well.
        struct.pack_into('<IBBHQ', raw, 0x800, 1, 0x20, 0, 0, 0)
        struct.pack_into('<IBBHQ', raw, 0x810, 1, 0xf, 1, 0, va+0x1540)
        raw[0x901:0x901+len(d.SYMBOL)+1] = d.SYMBOL+b'\0'
    return bytes(raw)


class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.raw = record()

    def test_all_states_raw_never_attribute(self):
        for state in range(4):
            r=d.decode_unbound(record(state))
            self.assertEqual(r['state'],state)
            self.assertFalse(r['identity_bound'])
            self.assertFalse(r['expiry_attributed_to_selected_image'])
            self.assertFalse(r['reset_proven'])

    def test_size_magic_version_state(self):
        for raw in (self.raw[:-1], self.raw+b'\0', bytes(128)):
            with self.assertRaises(ValueError):d.decode_unbound(raw)
        for offset,value in ((8,2),(12,4)):
            raw=self.raw.copy();struct.pack_into('<I',raw,offset,value)
            with self.assertRaises(ValueError):d.decode_unbound(raw)

    def test_reserved_flags_seconds_attempts(self):
        for offset,value in ((28,1),(92,1),(124,1),(24,4),(24,0),(16,59),(16,1801),(20,0)):
            raw=self.raw.copy();struct.pack_into('<I',raw,offset,value)
            with self.assertRaises(ValueError):d.decode_unbound(raw)

    def test_torn_or_inconsistent_states(self):
        for state in (0,1):
            raw=self.raw.copy();struct.pack_into('<I',raw,12,state)
            with self.assertRaises(ValueError):d.decode_unbound(raw)
        for offset,value in ((32,68*10**9),(40,68*10**9),(48,66*10**9),(40,56*10**9)):
            raw=self.raw.copy();struct.pack_into('<Q',raw,offset,value)
            with self.assertRaises(ValueError):d.decode_unbound(raw)

    def test_corrupt_length_is_explicit_not_dereferenced(self):
        raw=self.raw.copy();struct.pack_into('<I',raw,56,0xffffffff)
        with self.assertRaises(ValueError):d.decode_unbound(raw)
        struct.pack_into('<I',raw,24,3)
        self.assertEqual(d.decode_unbound(raw)['log_length_before'],0xffffffff)
        struct.pack_into('<I',raw,56,0)
        with self.assertRaises(ValueError):d.decode_unbound(raw)

    def fixture(self):
        kernel,symbol=macho(False),macho(True)
        identity='42'*32
        module_path=Path(d.__file__).resolve().parents[2]/'physical/trace_record.py'
        spec=importlib.util.spec_from_file_location('fixture_trace',module_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        trace=bytearray(module.initialized(bytes.fromhex(identity)))
        for off,value in ((48,10),(56,2**64-1-10),(64,10),(72,2**64-1-10),(80,9),(128,0xd0000000)):
            struct.pack_into('<Q',trace,off,value)
        segments,_=d.macho(kernel)
        manifest=dict(kernel_sha256=d.sha(kernel),image_sha256='12'*32,trace=dict(identity=identity),
            segments=[dict(offset=0x3b20000,**{k:s[k] for k in ('vmsize','fileoff','filesize')}) for s in segments])
        binding=dict(format=1,kernel_sha256=d.sha(kernel),symbol_sha256=d.sha(symbol),
            image_sha256='12'*32,trace_identity=identity,symbol_va=0xfffffff007b21540,physical_address=0xd3b21540)
        b=json.dumps(binding).encode()
        return dict(physical_address=0xd3b21540,kernel_bytes=kernel,symbol_bytes=symbol,
                    manifest=manifest,trace_bytes=trace,binding_bytes=b,binding_sha256=d.sha(b))

    def test_verified_binding_and_no_reset_claim(self):
        result=d.decode_bound(self.raw,**self.fixture())
        self.assertTrue(result['identity_bound'])
        self.assertTrue(result['expiry_attributed_to_selected_image'])
        self.assertTrue(result['cache_clean_attributed_to_selected_image'])
        self.assertFalse(result['reset_proven'])
        self.assertFalse(result['strip_equivalence_verified_here'])

    def test_wrong_frozen_files_binding_and_physical_address(self):
        for name,value in (('binding_sha256','00'*32),('physical_address',0xd3b21580),
                           ('kernel_bytes',macho(True)),('symbol_bytes',macho(False))):
            args=self.fixture();args[name]=value
            with self.assertRaises(ValueError):d.decode_bound(self.raw,**args)

    def test_stale_trace_wrong_segment_and_identity(self):
        for change in ('stale','unexecuted','offset','segment','identity'):
            args=self.fixture()
            if change=='stale':args['trace_bytes'][16]^=1
            elif change=='unexecuted':struct.pack_into('<Q',args['trace_bytes'],64,0)
            elif change=='offset':args['manifest']['segments'][0]['offset']+=64
            elif change=='segment':args['manifest']['segments'][0]['vmsize']+=64
            else:args['manifest']['trace']['identity']='43'*32
            with self.assertRaises(ValueError):d.decode_bound(self.raw,**args)

    def test_bad_macho_bounds_and_missing_symbol(self):
        for raw in (b'',macho(False),macho(True)[:100]):
            with self.assertRaises((ValueError,struct.error)):d.macho(raw,True)
        raw=bytearray(macho(True));struct.pack_into('<I',raw,0x810,999999)
        with self.assertRaises(ValueError):d.macho(raw,True)


if __name__=='__main__':unittest.main()
