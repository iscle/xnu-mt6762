#!/usr/bin/env python3
"""Decode one build-bound RAM trace; no device access or retention assumption."""
import argparse
import json
from pathlib import Path
import struct

OFFSET = 0x4000
ADDRESS = 0x40080000 + OFFSET
SIZE = 256
MAGIC = b'MTKTRC01'
PHASES = {0:'initialized-file-only', 1:'safe-entry', 2:'EL1', 3:'C-entry',
          4:'CPU-timer-identity', 5:'FDT-admitted', 6:'console-checked',
          7:'RAM-window-selected', 8:'kernel-copied', 9:'arguments-ready',
          10:'about-to-branch-to-XNU', 254:'refused', 255:'exception'}
FIELDS = ('phase', 'phase_inverse', 'sequence', 'sequence_inverse',
          'previous_phase', 'detail', 'original_el', 'fdt', 'midr', 'frequency',
          'ram', 'args', 'entry', 'esr', 'far', 'elr', 'spsr', 'exception_el',
          'entry_sctlr', 'mpidr')
MASK = (1 << 64) - 1


def initialized(identity):
    if len(identity) != 32:
        raise ValueError('identity must have32 bytes')
    return (MAGIC + struct.pack('<II', 1, SIZE) + identity +
            struct.pack('<4Q', 0, MASK, 0, MASK) + bytes(SIZE - 80))


def decode(data, identity):
    if len(data) != SIZE or len(identity) != 32:
        raise ValueError('exact256-byte trace and32-byte expected identity required')
    if data[:8] != MAGIC or struct.unpack_from('<II', data, 8) != (1, SIZE):
        raise ValueError('malformed trace magic/version/size')
    if data[16:48] != identity:
        raise ValueError('stale or different-build trace identity')
    values = dict(zip(FIELDS, struct.unpack_from('<20Q', data, 48)))
    if values['phase'] not in PHASES:
        raise ValueError('unknown trace phase')
    if values['phase'] ^ values['phase_inverse'] != MASK or values['sequence'] ^ values['sequence_inverse'] != MASK:
        raise ValueError('torn or malformed trace commit')
    if any(data[208:]):
        raise ValueError('nonzero reserved trace bytes')
    if not values['sequence']:
        if data != initialized(identity):
            raise ValueError('malformed initialized trace')
    elif not values['phase'] or values['previous_phase'] not in PHASES:
        raise ValueError('malformed executed trace')
    values.update(phase_name=PHASES[values['phase']], identity=identity.hex(),
                  executed=bool(values['sequence']), proves_xnu_executed=False,
                  physical_ram_retention_proven=False)
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    print(json.dumps(decode(args.record.read_bytes(), bytes.fromhex(manifest['trace']['identity'])), indent=2))


if __name__ == '__main__':
    main()
