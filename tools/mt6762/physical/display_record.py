#!/usr/bin/env python3
"""Decode the loader's build-bound display validation; never assert ownership."""
import argparse
import json
from pathlib import Path
import struct

OFFSET, ADDRESS, SIZE = 0x4100, 0x40084100, 512
MAGIC = b'MTKDSP01'
STATES = ('untouched', 'tag', 'bounds', 'reservation', 'power', 'gates',
          'sources', 'scanout', 'accepted', 'reading-incomplete')
SNAPSHOT = ('en', 'sources', 'ext_sources', 'roi', 'con', 'address', 'pitch',
            'size', 'offset', 'clip', 'rdma', 'downstream_rdma', 'dsi_start',
            'dsi_mode', 'dsi_lanes', 'dsi_active', 'dsi_ps', 'dsi_vsa',
            'dsi_vbp', 'dsi_vfp')


def initialized(identity):
    if len(identity) != 32:
        raise ValueError('32-byte build identity required')
    return (MAGIC + struct.pack('<II', 1, SIZE) + identity +
            struct.pack('<4I', 0, 0, 0, 0xffffffff) + bytes(SIZE - 64))


def decode(data, identity):
    if len(data) != SIZE or len(identity) != 32:
        raise ValueError('exact512-byte display record and32-byte identity required')
    if data[:8] != MAGIC or struct.unpack_from('<II', data, 8) != (1, SIZE):
        raise ValueError('malformed display magic/version/size')
    if data[16:48] != identity:
        raise ValueError('stale or different-build display record')
    state, pass_number, mask, inverse = struct.unpack_from('<4I', data, 48)
    if state >= len(STATES) or state ^ inverse != 0xffffffff or any(data[432:]):
        raise ValueError('malformed or torn display commit')
    expected_masks = {0:(0,), 1:(1,), 2:(1,), 3:(1,), 4:(3,), 5:(7,), 6:(15,31), 7:(31,), 8:(31,)}
    if mask & ~31 or (state != 9 and mask not in expected_masks[state]):
        raise ValueError('invalid display read mask')
    if ((state == 0 and data != initialized(identity)) or
        (state in (1,2,3) and pass_number != 0) or
        (state in (4,5,6,7) and pass_number not in (1,2)) or
        (state == 8 and pass_number != 2) or pass_number > 2):
        raise ValueError('invalid display pass')
    result = dict(state=state, state_name=STATES[state], pass_number=pass_number,
                  read_mask=mask, identity=identity.hex(), accepted=state == 8,
                  native_ownership=False, physical_retention_proven=False)
    if mask & 1:
        base, size, present, found = struct.unpack_from('<2Q2I', data, 64)
        result['tag'] = dict(base=base, size=size, present=present, found=found)
    if mask & 2:
        result['power'] = list(struct.unpack_from('<3I', data, 88))
    if mask & 4:
        result['gates'], = struct.unpack_from('<I', data, 100)
    if mask & 8:
        result['sources'], = struct.unpack_from('<I', data, 104)
    if mask & 16:
        result['layer'], = struct.unpack_from('<I', data, 108)
        if not 0 < result['sources'] <= 15:
            raise ValueError('invalid observed display sources')
        result['scanout'] = {str(i):dict(zip(SNAPSHOT, struct.unpack_from('<20I', data, 112+i*80)))
                             for i in range(4) if result['sources'] & (1 << i)}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    identity = bytes.fromhex(json.loads(args.manifest.read_text())['trace']['identity'])
    print(json.dumps(decode(args.record.read_bytes(), identity), indent=2))
