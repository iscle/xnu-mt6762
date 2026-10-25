#!/usr/bin/env python3
"""Offline exact-image patch. No transport or flashing functions."""
import argparse, hashlib, json, struct
from pathlib import Path
SHA = '5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
SIZE = 0x100000
BASE = 0x47fffe00
SITE = 0x4803799a
OFFSET = SITE - BASE
BEFORE = bytes.fromhex('0bf077f8')
AFTER = bytes.fromhex('00bf00bf')
def digest(b): return hashlib.sha256(b).hexdigest()
def patch(b):
    if len(b) != SIZE or digest(b) != SHA:
        raise ValueError('Not the pinned, complete stock LK partition')
    if b[OFFSET:OFFSET+4] != BEFORE:
        raise ValueError('Unexpected call-site preimage')
    magic, size = struct.unpack_from('<II', b)
    if magic != 0x58881688 or size != 0xac5bc or not 512 <= OFFSET < 512 + size - 4:
        raise ValueError('Unexpected header/load extent')
    out = b[:OFFSET] + AFTER + b[OFFSET+4:]
    assert len(out) == SIZE and out[:OFFSET] == b[:OFFSET] and out[OFFSET+4:] == b[OFFSET+4:]
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stock',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args(); b=a.stock.read_bytes(); out=patch(b)
    report={'authority':'Offline exact-stock instruction replacement; no physical execution or authentication proof',
      'input_sha256':digest(b),'output_sha256':digest(out),'partition_bytes':len(out),
      'patch':{'virtual_address':hex(SITE),'file_offset':hex(OFFSET),'before':BEFORE.hex(),'after':AFTER.hex(),
      'old_instruction':'bl #0x48042a8c','new_instructions':['nop','nop']},
      'byte_diffs':[{'offset':hex(i),'before':x,'after':y} for i,(x,y) in enumerate(zip(b,out)) if x!=y],
      'header':{'bytes':512,'declared_payload_bytes':0xac5bc,'declared_payload_end':hex(512+0xac5bc),'unchanged':True},
      'unchanged':['Every byte outside the four-byte call','Warning strings, including original 5 seconds wording','State dispatcher and security policy','Both watchdog refreshes','All other delay calls','Partition header, embedded DT and trailer'],
      'limitations':['No signature recomputation','No proof that the normal preloader accepts modified LK','BootROM acceptance of a DA does not establish normal LK verification policy','No phone operation or flashing mechanism']}
    with a.output.open('xb') as f:f.write(out)
    with a.report.open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps({'output':str(a.output),'sha256':digest(out),'changed_bytes':len(report['byte_diffs'])}))
if __name__=='__main__':main()
