#!/usr/bin/env python3
"""Extract exact stock SSPM mailbox descriptors, not logs or identifiers."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('image',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args();b=a.image.read_bytes();digest=hashlib.sha256(b).hexdigest()
if digest!='82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b':
 raise SystemExit('Unsupported Image digest; addresses are specific to this stock build')
base=0xffffff8008080000
send=[]
for pin in range(2):
 va=0xffffff8009846a30+80*pin+64
 raw=struct.unpack_from('<I',b,va-base)[0]
 send.append(dict(pin=pin,descriptor_va=hex(va),raw=hex(raw),mailbox=raw&7,
                  slot=(raw>>3)&63,words=(raw>>9)&63,return_data=(raw>>16)&1))
recv_va=0xffffff8009846df0+16+8
raw=struct.unpack_from('<I',b,recv_va-base)[0]
result=dict(image_sha256=digest,send_descriptor_stride=80,send=send,
 cpu_notification=dict(descriptor_va=hex(recv_va),raw=hex(raw),mailbox=raw&7,
                       slot=(raw>>3)&63,words=(raw>>9)&63),
 mailbox0_info=dict(va='0xffffff8009846e30',raw=hex(struct.unpack_from('<I',b,0xffffff8009846e30-base)[0])))
a.output.write_text(json.dumps(result,indent=2)+'\n')
