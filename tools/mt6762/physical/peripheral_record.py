"""Versioned passive register record, bound to one physical Image identity."""
import json
from pathlib import Path
import struct

HERE=Path(__file__).resolve().parent
SIZE=4096
OFFSET=0x4400
ADDRESS=0x40080000+OFFSET
MAGIC=b'MTKPER01'

def registers():
    table=json.loads((HERE/'peripheral-registers.json').read_text())['registers']
    assert 0<len(table)<=250
    seen=set();last=0
    for e in table:
        a=int(e['address'],0);w=e['width'];g=e['group']
        assert a not in seen and 0<a<2**32 and w in (2,4) and a%w==0 and last<=g<=5
        seen.add(a);last=g
    return table

def initialized(identity):
    if len(identity)!=32:raise ValueError('Require Image identity')
    raw=bytearray(SIZE)
    struct.pack_into('<8sII32s4I4Q',raw,0,MAGIC,1,SIZE,identity,0,0xffffffff,0,0,0,0,0,0)
    for n,e in enumerate(registers()):
        struct.pack_into('<IBBHII',raw,96+n*16,int(e['address'],0),e['width'],e['group'],0,0,0)
    return bytes(raw)

def decode(raw,identity):
    if len(raw)!=SIZE or raw[:16]!=struct.pack('<8sII',MAGIC,1,SIZE) or raw[16:48]!=identity:
        raise ValueError('Peripheral record format or Image identity mismatch')
    state,inverse,passes,index=struct.unpack_from('<4I',raw,48)
    if state not in (0,1,2) or inverse!=state^0xffffffff or passes>2 or index>=250:
        raise ValueError('Incomplete/corrupt peripheral state')
    table=registers()
    if state==0 and raw!=initialized(identity):raise ValueError('Changed unexecuted peripheral record')
    if state==2 and (passes!=2 or index!=len(table)-1):raise ValueError('Incomplete completed peripheral record')
    times=struct.unpack_from('<4Q',raw,64);result=[]
    if state==2 and any(times[n+2]<times[n] for n in (0,1)):
        raise ValueError('Invalid peripheral timestamps')
    for n,e in enumerate(table):
        address,width,group,valid,first,second=struct.unpack_from('<IBBHII',raw,96+n*16)
        if (address,width,group)!=(int(e['address'],0),e['width'],e['group']) or valid>3:
            raise ValueError('Register allowlist/layout mismatch')
        if (not valid&1 and first) or (not valid&2 and second) or (width==2 and (first>65535 or second>65535)):
            raise ValueError('Invalid unread or narrow register value')
        result.append(dict(e,valid=valid,first=first if valid&1 else None,
                           second=second if valid&2 else None,stable=valid==3 and first==second))
    if any(raw[96+len(result)*16:]):raise ValueError('Unexpected extra register entries')
    return dict(state=state,pass_number=passes,last_index=index,began_ticks=times[:2],
        ended_ticks=times[2:],counter_hz=13000000,registers=result,
        lk_card_metadata=lk_card_metadata(result),
        ownership_granted=False,mmio_writes=False)

def lk_card_metadata(entries):
    """Interpret only the pinned LK's stable, pointer-linked static objects.

    This is a corroborating software snapshot, never card/queue ownership or
    live EXT_CSD evidence. In particular, no captured pointer is dereferenced.
    """
    values={int(e['address'],0):e['first'] for e in entries if e['stable']}
    words=(0x4a0301c3,0x00c0eb03,0x4410447a,0xbf004770,0x000fb12c,
           0x4a030203,0x2080ebc3,0x4410447a,0xbf004770,0x000fb228)
    if any(values.get(0x4804bb18+4*n)!=v for n,v in enumerate(words)):
        return dict(valid=False,reason='LK getter code absent, unstable or mismatched')
    host,card=0x48146c50,0x48146d60
    required={host:card,host+0x28:0x11230000,host+0x44:512,
              card:host,card+8:512,card+0x1c:1}
    if any(values.get(a)!=v for a,v in required.items()):
        return dict(valid=False,reason='LK host/card linkage, type or geometry mismatch')
    fields={name:values.get(card+offset) for name,offset in
            (('sectors',4),('ocr',12),('rca',24),('state_ready',32))}
    if (any(v is None for v in fields.values()) or not 0<fields['sectors']<2**31 or
        not 0<fields['rca']<=65535 or fields['ocr']&0xc0000000!=0xc0000000 or
        not fields['state_ready']&0x10 or fields['state_ready']>>16!=1):
        return dict(valid=False,reason='LK card addressing/readiness metadata incomplete')
    return dict(valid=True,**fields,ownership_granted=False,
                authority='stable exact-LK software metadata; requires live CMD13 and EXT_CSD')
