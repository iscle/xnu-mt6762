#!/usr/bin/env python3
"""Decode passive brightness snapshots; no inferred native ownership."""
import argparse
import json
from pathlib import Path
import struct

OFFSET, ADDRESS, SIZE = 0x4300, 0x40084300, 256
MAGIC = b'MTKPWM01'
STATES = ('untouched', 'reading-incomplete', 'unavailable', 'complete')
FIELDS = ('mask','power0','power1','power_control','top','infra','gpio','ulposc',
          'enable','commit','con0','con1','debug')


def initialized(identity):
    if len(identity) != 32:
        raise ValueError('32-byte build identity required')
    return (MAGIC + struct.pack('<II', 1, SIZE) + identity +
            struct.pack('<4I', 0, 0xffffffff, 0, 0) + bytes(SIZE - 64))


def decode(data, identity):
    if len(data) != SIZE or len(identity) != 32:
        raise ValueError('exact PWM record and identity sizes required')
    if data[:16] != MAGIC + struct.pack('<II', 1, SIZE) or data[16:48] != identity:
        raise ValueError('malformed or different-build PWM record')
    state, inverse, passes, reserved = struct.unpack_from('<4I', data, 48)
    if (state >= len(STATES) or state ^ inverse != 0xffffffff or reserved or
        passes > 2 or any(data[192:]) or any(data[116:128]) or any(data[180:192])):
        raise ValueError('malformed or torn PWM record')
    if ((state == 0 and data != initialized(identity)) or
        (state in (2,3) and passes == 0) or (state == 3 and passes != 2)):
        raise ValueError('invalid PWM state/pass')
    observations = []
    for i in range(2):
        raw = struct.unpack_from('<16I', data, 64 + i*64)
        s = dict(zip(FIELDS, raw))
        mask = s['mask']
        if mask not in (0,1,3,7,15,23,31) or (i >= passes and any(raw)):
            raise ValueError('invalid PWM snapshot mask')
        if state == 3 and mask not in (23,31):
            raise ValueError('missing completed PWM reads')
        groups = ((1, ('power0','power1','power_control')),
                  (2, ('top','infra')), (4, ('gpio',)), (8, ('ulposc',)),
                  (16, ('enable','commit','con0','con1','debug')))
        observed = {'read_mask':mask}
        for bit, names in groups:
            if mask & bit:
                observed.update({k:s[k] for k in names})
        if mask & 2:
            observed['parent_selector'] = (s['top'] >> 24) & 3
        if mask & 4:
            observed['gpio43_mode'] = (s['gpio'] >> 12) & 15
        if mask & 16:
            observed.update(divider=(s['con0'] >> 16) & 0x3ff,
                            period=s['con1'] & 0x3ff,
                            duty=(s['con1'] >> 16) & 0x1fff)
        if i < passes:
            observations.append(observed)
    return dict(state=state, state_name=STATES[state], pass_number=passes,
                identity=identity.hex(), snapshots=observations,
                stable_complete=state == 3 and observations[0] == observations[1],
                native_ownership=False, register_writes=False)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('record',type=Path);p.add_argument('--manifest',type=Path,required=True)
    a=p.parse_args();identity=bytes.fromhex(json.loads(a.manifest.read_text())['trace']['identity'])
    print(json.dumps(decode(a.record.read_bytes(),identity),indent=2))
