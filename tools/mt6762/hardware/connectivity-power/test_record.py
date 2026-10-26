#!/usr/bin/env python3
"""Cross-check decoder/initializer against records emitted by actual C code."""
from pathlib import Path
import struct
import sys
import record


def rejects(data, expected=None):
    try:
        record.decode(data, expected)
    except ValueError:
        return
    raise AssertionError('corrupt record admitted')


def main():
    success, failed, family, wrapped, disabled = (Path(x).read_bytes() for x in sys.argv[1:])
    identity = bytes((1, 2, 3, 4)) + bytes(28)
    initial = record.initialize(identity)
    assert record.decode(initial)['state_name'] == 'not-started'
    good = record.decode(success, identity)
    assert good['state_name'] == 'complete' and len(good['registers']) == 40
    assert all(r['valid'] == 3 for r in good['registers'])
    assert all(r['stable'] for i, r in enumerate(good['registers']) if i != 21)
    assert good['registers'][21]['value'] == [0x5700, 0x5701]
    assert not good['ownership_granted'] and not good['physical_retention_proven']
    # Both inactive states require pristine samples, not merely clear valid
    # bits. Exercise every value slot against Python's initializer and the
    # actual C-emitted DISABLED packet.
    assert record.decode(disabled, identity)['state_name'] == 'disabled'
    for inactive in (initial, disabled):
        for index in range(len(record.REGISTERS)):
            for sample in range(2):
                corrupt = bytearray(inactive)
                struct.pack_into('<I', corrupt, 112 + index*24 + 8 + sample*4, 1)
                rejects(corrupt)
    # Actual C code crosses UINT64_MAX during the first pass. A raw numeric
    # b0<=e0 rule would wrongly reject this valid packet.
    wrap = record.decode(wrapped, identity)
    assert wrap['began_ticks'][0] > wrap['ended_ticks'][0]
    assert wrap['state_name'] == 'complete'
    for actual in (success, wrapped):
        b0, b1, e0, e1 = struct.unpack_from('<QQQQ', actual, 64)
        mask = (1 << 64) - 1
        # Break each ordering boundary while retaining the original final
        # duration where possible. Both ordinary and wrapped clocks must fail.
        for offset, value in [(80, b0-1), (80, b1+1), (72, e0-1),
                              (72, e1+1), (88, b1-1), (64, e0+1)]:
            corrupt = bytearray(actual)
            struct.pack_into('<Q', corrupt, offset, value & mask)
            rejects(corrupt)
    # Equal timestamps are allowed: finite request counts also bound a frozen
    # counter, so timestamp ordering is non-strict inside the global budget.
    frozen = bytearray(success)
    struct.pack_into('<QQQQ', frozen, 64, 42, 42, 42, 42)
    assert record.decode(frozen)['state_name'] == 'complete'
    bad = record.decode(failed, identity)
    assert bad['state_name'] == 'failed' and bad['result'] == -2 and bad['transport_error'] == -77
    assert bad['pass_number'] == 2 and bad['index'] == 22
    assert bad['registers'][22]['valid'] == 1 and bad['registers'][22]['value'][1] is None
    assert bad['registers'][22]['error'][1] == -77
    assert bad['registers'][23]['error'][1] == record.NOT_READ
    mismatch = record.decode(family, identity)
    assert mismatch['result'] == -6 and mismatch['registers'][21]['value'][0] == 0x5801
    assert mismatch['registers'][22]['value'] == [None, None]
    corrupt = bytearray(family); struct.pack_into('<I', corrupt, 112 + 21*24 + 8, 0x5701); rejects(corrupt)
    rejects(success[:-1]); rejects(success + b'\0'); rejects(success, bytes(32))
    # Header, identity binding, commit pair, table shape, values, errors, padding.
    for offset, fmt, value in [(0, 'B', 0), (8, 'I', 2), (12, 'I', 1024),
        (48, 'I', 5), (52, 'I', 0), (56, 'I', 3), (60, 'I', 40),
        (96, 'I', 1), (100, 'I', 0), (104, 'i', -2),
        (112, 'I', 0x18000000), (116, 'B', 1), (117, 'B', 2),
        (118, 'H', 4), (128, 'i', -1), (112 + 21*24 + 8, 'I', 0x10000),
        (1072, 'B', 1)]:
        data = bytearray(success); struct.pack_into('<' + fmt, data, offset, value); rejects(data)
    for r in good['registers']:
        address = int(r['address'], 16)
        assert not 0x18000000 <= address < 0x19000000
        assert r['width'] == (4 if r['bus'] == 'ap' else 2)
    assert initial[112:120] == success[112:120][:6] + b'\0\0'
    print('connectivity record: C/Python ABI, inactive zeros, ordered/wrapped timestamps, partial failure, payload binding, corruption and domain exclusions PASS')


if __name__ == '__main__':
    main()
