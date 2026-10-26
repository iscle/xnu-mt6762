#!/usr/bin/env python3
"""Initialize/decode the4096-byte version1 passive connectivity record."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

MAGIC = b'MTKCONN1'
SIZE = 4096
HEADER = struct.Struct('<8sII32sIIIIQQQQIIii')
ENTRY = struct.Struct('<IBBHIIii')
NOT_READ = -(1 << 31)
NAMES = {0: 'not-started', 1: 'disabled', 2: 'reading', 3: 'complete', 4: 'failed'}
CATALOG = json.loads(Path(__file__).with_name('registers.json').read_text())
REGISTERS = [(int(r['address'], 16), 0, 4, r['meaning']) for r in CATALOG['ap']]
REGISTERS += [(int(r['word'], 16), 1, 2, r['meaning']) for r in CATALOG['pmic']]
assert HEADER.size == 112 and ENTRY.size == 24 and len(REGISTERS) == 40


def identity_bytes(value):
    try:
        result = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError('identity must be64 hexadecimal digits') from error
    if len(result) != 32:
        raise ValueError('identity must be32 bytes')
    return result


def initialize(identity):
    if len(identity) != 32:
        raise ValueError('identity must be32 bytes')
    data = bytearray(SIZE)
    HEADER.pack_into(data, 0, MAGIC, 1, SIZE, identity, 0, 0xffffffff, 0,
                     0xffffffff, 0, 0, 0, 0, 0, 0, 0, 0)
    for i, (address, bus, width, _) in enumerate(REGISTERS):
        ENTRY.pack_into(data, HEADER.size + i * ENTRY.size, address, bus, width,
                        0, 0, 0, NOT_READ, NOT_READ)
    return bytes(data)


def decode(data, expected_identity=None):
    if len(data) != SIZE:
        raise ValueError('record must be exactly4096 bytes')
    (magic, version, size, identity, state, inverse, pass_number, index,
     b0, b1, e0, e1, hz, budget_us, result, transport_error) = HEADER.unpack_from(data)
    if magic != MAGIC or version != 1 or size != SIZE:
        raise ValueError('unsupported record identity/version/size')
    if expected_identity is not None and identity != expected_identity:
        raise ValueError('payload identity mismatch')
    if state not in NAMES or inverse != state ^ 0xffffffff:
        raise ValueError('unknown or torn state commit')
    if pass_number > 2 or (index != 0xffffffff and index >= len(REGISTERS)):
        raise ValueError('invalid pass/index')
    if any(data[HEADER.size + ENTRY.size * len(REGISTERS):]):
        raise ValueError('version1 reserved bytes must be zero')
    rows = []
    for i, (address, bus, width, meaning) in enumerate(REGISTERS):
        actual, actual_bus, actual_width, valid, v0, v1, err0, err1 = ENTRY.unpack_from(data, HEADER.size + i * ENTRY.size)
        if (actual, actual_bus, actual_width) != (address, bus, width):
            raise ValueError(f'entry{i}: address/bus/width differs from fixed catalog')
        if valid & ~3:
            raise ValueError(f'entry{i}: unknown validity bit')
        values, errors = (v0, v1), (err0, err1)
        for p in range(2):
            if valid & (1 << p) and (errors[p] != 0 or (width == 2 and values[p] > 0xffff)):
                raise ValueError(f'entry{i}: invalid committed sample')
        rows.append({'address': hex(address), 'bus': 'ap' if bus == 0 else 'pmic',
                     'width': width, 'meaning': meaning, 'valid': valid,
                     'value': [values[p] if valid & (1 << p) else None for p in range(2)],
                     'raw_uncommitted_value': [None if valid & (1 << p) else values[p] for p in range(2)],
                     'error': list(errors), 'stable': v0 == v1 if valid == 3 else None})
    if state in (0, 1):
        if (pass_number or index != 0xffffffff or any((b0, b1, e0, e1, hz, budget_us, transport_error))
                or result != (1 if state == 1 else 0)
                or any(r['valid'] or r['error'] != [NOT_READ, NOT_READ]
                       or any(r['raw_uncommitted_value']) for r in rows)):
            raise ValueError('inactive record contains completed work')
    if state == 3:
        if (pass_number != 2 or index != len(REGISTERS) - 1 or result or transport_error or hz != 13000000
                or not 0 < budget_us <= 1000000 or any(r['valid'] != 3 for r in rows)):
            raise ValueError('incomplete or inconsistent COMPLETE record')
        # Anchor all four timestamps to the first start. Unsigned modular
        # offsets admit a real counter wrap, but not backwards/overlapping
        # passes hidden by an otherwise short final end-minus-start span.
        elapsed_e0, elapsed_b1, elapsed_e1 = (
            (tick - b0) & ((1 << 64) - 1) for tick in (e0, b1, e1))
        if not 0 <= elapsed_e0 <= elapsed_b1 <= elapsed_e1 < budget_us * 13:
            raise ValueError('complete record has inconsistent timestamps or exceeds time budget')
    if state == 3 and any((value >> 8) != 0x57 for value in rows[21]['value']):
        raise ValueError('COMPLETE record contains wrong PMIC family')
    if state == 4 and result not in (-1, -2, -3, -4, -5, -6):
        raise ValueError('FAILED record has no recognized failure result')
    if state == 4 and result == -6:
        if (pass_number not in (1, 2) or index != 21 or transport_error
                or not (rows[21]['valid'] & (1 << (pass_number - 1)))
                or rows[21]['value'][pass_number - 1] >> 8 == 0x57
                or any(r['valid'] & (1 << (pass_number - 1)) for r in rows[22:])):
            raise ValueError('inconsistent PMIC family failure')
    return {'format': 1, 'record_sha256': hashlib.sha256(data).hexdigest(),
            'identity': identity.hex(), 'state': state, 'state_name': NAMES[state],
            'pass_number': pass_number, 'index': index, 'began_ticks': [b0, b1],
            'ended_ticks': [e0, e1], 'counter_hz': hz, 'budget_us': budget_us,
            'result': result, 'transport_error': transport_error, 'registers': rows,
            'ownership_granted': False, 'survey_requests_pmic_writes': False,
            'physical_retention_proven': False,
            'limits': ['Sequential raw observations; no rail voltage or oscillator frequency measurement.',
                       'A valid record/identity is not independent proof of physical execution or permission.',
                       'Uncommitted values are retained only as incomplete bytes, never valid samples.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('initialize')
    init.add_argument('--identity', required=True)
    init.add_argument('--output', type=Path, required=True)
    show = sub.add_parser('decode')
    show.add_argument('record', type=Path)
    show.add_argument('--expected-identity')
    args = parser.parse_args()
    if args.action == 'initialize':
        args.output.write_bytes(initialize(identity_bytes(args.identity)))
    else:
        expected = identity_bytes(args.expected_identity) if args.expected_identity else None
        print(json.dumps(decode(args.record.read_bytes(), expected), indent=2))


if __name__ == '__main__':
    main()
