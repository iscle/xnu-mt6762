#!/usr/bin/env python3
"""Opt-in, volatile DA2 heap reservation. No USB, device I/O or persistent writes.

Wrap the existing XFlashExt.patch_da2 method before patch_da calls it, so the
existing caller recomputes DA1's DA2 hash AFTER this transformation. Never apply
the transformation after fix_hash or to a running agent. No auto-installation.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

LOADER_SHA='aef234190ccb8145d2e3b8459741e9adb70f2caa8481aa216c1b25152afaca1f'
DA2_SHA='658ff869c301fadc1a84a9409a55b5b5bdcf01524a1f904aad29a89a07ef2dec'
DA2_OFFSET=0x7538a4
DA2_LENGTH=0x5118c
OLD_BASE=0x4005e2a0
NEW_BASE=0x40090000
HEAP_END=0x68000000
PATCH_OFFSETS=(0xa340,0xadf8)
# Reject any preceding security transformation that also changes the audited
# startup, allocator, getter, literals, stack initialization or allocation ABI.
PROTECTED_SPANS=((0,0x124),(0x7e8,0x810),(0xb84,0xbb8),(0xbfc,0xd20),
                 (0xe74,0xefc),(0xa338,0xa348),(0xac18,0xae32))

def sha(b):return hashlib.sha256(b).hexdigest()
def extract_original(loader):
    if sha(loader)!=LOADER_SHA:raise ValueError('loader digest mismatch')
    off=0x6c+22*0xdc
    head=struct.unpack_from('<10H',loader,off)
    region=struct.unpack_from('<5I',loader,off+20+2*20)
    if head[1]!=0x6765 or head[9]!=3 or region!=(DA2_OFFSET,DA2_LENGTH,0x40000000,0x5108c,0x100):
        raise ValueError('DA entry/region mismatch')
    da=loader[DA2_OFFSET:DA2_OFFSET+DA2_LENGTH]
    if sha(da)!=DA2_SHA:raise ValueError('original DA2 mismatch')
    return da

def reserve(original,already_patched):
    """Return bytes+manifest; only two literal words change from prior output."""
    if sha(original)!=DA2_SHA:raise ValueError('original DA2 digest mismatch')
    candidate=bytes(already_patched)
    if len(candidate)!=DA2_LENGTH:raise ValueError('full DA2 region including signature required')
    for lo,hi in PROTECTED_SPANS:
        if candidate[lo:hi]!=original[lo:hi]:raise ValueError(f'audited preimage changed at {lo:#x}..{hi:#x}')
    expected={0x120:OLD_BASE,0xa340:OLD_BASE,0xadf8:OLD_BASE,0xa344:HEAP_END,0x11c:0x40051090}
    for offset,value in expected.items():
        if struct.unpack_from('<I',candidate,offset)[0]!=value:raise ValueError('literal preimage mismatch')
    # Fixed new boundary: 64KiB-aligned, above full BSS and the whole 256-byte trace.
    if NEW_BASE&0xffff or not OLD_BASE<0x40084000<0x40084100<=NEW_BASE<HEAP_END:
        raise ValueError('reservation bounds invalid')
    out=bytearray(candidate)
    for offset in PATCH_OFFSETS:struct.pack_into('<I',out,offset,NEW_BASE)
    out=bytes(out)
    changed=[i for i,(x,y) in enumerate(zip(candidate,out)) if x!=y]
    if not all(any(off<=i<off+4 for off in PATCH_OFFSETS) for i in changed):raise AssertionError('unexpected delta')
    if out[:0x124]!=candidate[:0x124]:raise AssertionError('startup/BSS changed')
    manifest={'loader_sha256':LOADER_SHA,'entry_index_zero_based':22,'hwcode':'0x6765',
       'original_da2_sha256':DA2_SHA,'after_existing_patcher_sha256':sha(candidate),
       'reserved_da2_sha256':sha(out),'length':len(out),
       'patches':[{'offset':hex(o),'runtime_literal_address':hex(0x40000000+o),
                   'before':hex(OLD_BASE),'after':hex(NEW_BASE)} for o in PATCH_OFFSETS],
       'changed_byte_offsets':[hex(i) for i in changed],
       'heap_before':[hex(OLD_BASE),hex(HEAP_END)],'heap_after':[hex(NEW_BASE),hex(HEAP_END)],
       'bss_unchanged':['0x40051090','0x4005e2a0'],'trace':['0x40084000','0x40084100'],
       'removed_heap_bytes':NEW_BASE-OLD_BASE,
       'scope':'Volatile DA2 allocation parameter only; no new code, callback, physical writes or flash image.',
       'unknown_retention':['Preloader DRAM initialization','DA1 and BROM use','non-heap DMA and fixed buffers','reset/power retention']}
    return out,manifest

def wrap_patcher(prior,loader_bytes,record_manifest):
    """Explicit opt-in hook for one process; does not install itself.

    xft.patch_da2 = wrap_patcher(xft.patch_da2, loader_bytes, record_manifest)
    Existing xflash.patch_da then calls fix_hash on the returned bytes. Caller
    must refuse its unpatched fallback path and require record_manifest called
    before allowing upload. Record callback errors abort the caller.
    """
    original=extract_original(loader_bytes)
    def wrapped(da2):
        if bytes(da2)!=original:raise ValueError('selected DA2 is not pinned original')
        after_security=prior(da2)
        out,manifest=reserve(original,after_security)
        record_manifest(manifest)
        return bytearray(out)
    return wrapped

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--loader',required=True,type=Path)
    p.add_argument('--after-existing-patcher',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--manifest',required=True,type=Path)
    a=p.parse_args()
    if a.output.exists() or a.manifest.exists():p.error('new output paths required')
    out,manifest=reserve(extract_original(a.loader.read_bytes()),a.after_existing_patcher.read_bytes())
    with a.output.open('xb') as f:f.write(out)
    with a.manifest.open('x') as f:json.dump(manifest,f,indent=2);f.write('\n')
    print(json.dumps({'output_sha256':sha(out),'heap_base':hex(NEW_BASE),'bytes_removed':NEW_BASE-OLD_BASE}))
if __name__=='__main__':main()
