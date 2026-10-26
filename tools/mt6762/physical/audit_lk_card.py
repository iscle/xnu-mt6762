#!/usr/bin/env python3
"""Reproduce bounded LK host/card metadata addresses without device access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

def audit(data):
    digest=hashlib.sha256(data).hexdigest()
    if digest!='5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a':
        raise ValueError('Require exact stock LK')
    base=0x47fffe00
    def word(address):return struct.unpack_from('<I',data,address-base)[0]
    words=[word(a) for a in range(0x4804bb18,0x4804bb40,4)]
    assert words==[0x4a0301c3,0xc0eb03,0x4410447a,0xbf004770,0xfb12c,
                   0x4a030203,0x2080ebc3,0x4410447a,0xbf004770,0xfb228]
    # Exact Thumb getters: index0; LDR literal followed by ADD R2,PC.
    host=0x4804bb24+word(0x4804bb28)
    card=0x4804bb38+word(0x4804bb3c)
    assert (host,card)==(0x48146c50,0x48146d60)
    # CMD13 loads RCA from card+0x18; init stores OCR at card+0x0c.
    assert struct.unpack_from('<H',data,0x4804c3fc-base)[0]==0x698b
    assert struct.unpack_from('<H',data,0x4804d002-base)[0]==0x60fb
    return dict(stock_lk_sha256=digest,lk_image_address=hex(base),
        getter_address='0x4804bb18',getter_words=[hex(v) for v in words],
        host_address=hex(host),card_address=hex(card),
        card_ocr_address=hex(card+12),card_rca_address=hex(card+24),
        excluded_cid_start=hex(card+36),
        claims=['Static address/code audit only','No phone I/O or card ownership proof'],
        capture_contract='Read fixed words twice before kernel entry; validate code, linkage, geometry and addressing; never follow pointers')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lk',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();result=audit(a.lk.read_bytes())
    with a.out.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print('PASS: exact stock LK getters, OCR/RCA instructions and bounded static addresses')

if __name__=='__main__':main()
