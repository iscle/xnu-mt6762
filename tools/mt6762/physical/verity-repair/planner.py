#!/usr/bin/env python3
"""Bounded, offline planning for the audited LK's seccfg warning state.

No device API is imported. Authentication is supplied by the separate adapter;
structural inspection alone never labels a candidate authenticated.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

PARTITION_SIZE = 8 * 1024 * 1024
KEY = b'avb.managed_verity_mode'
PERSIST_OFFSET = 0x200
MAX_RECORDS = 8


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect(data):
    if len(data) != PARTITION_SIZE:
        raise ValueError('Expected complete 8MiB seccfg capture')
    words = struct.unpack_from('<7I', data)
    if words[:3] != (0x4d4d4d4d, 4, 60) or words[6] != 0x45454545:
        raise ValueError('Unsupported authenticated header layout')
    if words[3] != 3:
        raise ValueError('Require already unlocked state3; never lock/unlock here')
    if words[4] not in (0, 1):
        raise ValueError('Unknown exact-LK dm-verity status')
    if struct.unpack_from('>3I', data, PERSIST_OFFSET) != (0x90790922, 1, 0):
        raise ValueError('Unsupported persistent header')
    if any(data[0x20c:0x240]):
        raise ValueError('Nonzero unknown persistent header extension')
    pos = 0x240
    keys = set()
    records = []
    value_offset = None
    while True:
        if pos + 12 > len(data):
            raise ValueError('Truncated descriptor')
        magic, key_size, value_size = struct.unpack_from('>3I', data, pos)
        if magic == 0:
            if key_size or value_size:
                raise ValueError('Malformed persistent terminator')
            break
        if magic != 0x90790804 or len(records) >= MAX_RECORDS:
            raise ValueError('Unknown descriptor or excessive record count')
        # Deliberately tighter than arbitrary partition size; no guessed allocation.
        if not 1 <= key_size <= 1024 or not 1 <= value_size <= 65536:
            raise ValueError('Unsupported descriptor size')
        end = pos + 12 + key_size + value_size
        if end + 12 > len(data):
            raise ValueError('Descriptor exceeds partition')
        key = bytes(data[pos + 12:pos + 12 + key_size])
        if key in keys:
            raise ValueError('Duplicate persistent key')
        keys.add(key)
        if key == KEY:
            if key_size != 23 or value_size != 32:
                raise ValueError('Managed-verity key/value must be23/32 bytes')
            value_offset = pos + 12 + key_size
        records.append({'descriptor_offset': pos, 'key_size': key_size,
                        'value_size': value_size, 'is_managed_verity': key == KEY})
        pos = end  # Packed descriptors: no alignment between records.
    return {'input_sha256': sha(data), 'partition_size': len(data),
            'lock_state': words[3], 'dm_verity_status': words[4],
            'sboot_runtime': words[5], 'records': records,
            'managed_value_offset': value_offset,
            'authenticated': False}


def build_candidate(data, authenticate_header):
    """Callback returns the existing device's encrypted SHA256 for 28 bytes.

    The callback is not trusted to change anything else, and this pure function
    does not claim to verify the callback's cryptographic result.
    """
    info = inspect(data)
    result = bytearray(data)
    struct.pack_into('<I', result, 0x10, 0)
    if info['dm_verity_status']:
        encrypted_hash = authenticate_header(bytes(result[:28]))
        if not isinstance(encrypted_hash, bytes) or len(encrypted_hash) != 32:
            raise ValueError('Authentication callback must return exactly32 bytes')
        result[28:60] = encrypted_hash
    offset = info['managed_value_offset']
    if offset is not None:
        result[offset:offset + 32] = bytes(32)
    result = bytes(result)
    allowed = [(0x10, 0x14), (0x1c, 0x3c)]
    if offset is not None:
        allowed.append((offset, offset + 32))
    changes = [n for n, (a, b) in enumerate(zip(data, result)) if a != b]
    if any(not any(lo <= n < hi for lo, hi in allowed) for n in changes):
        raise ValueError('Unexpected mutation outside allowlist')
    after = inspect(result)
    if after['lock_state'] != 3 or after['dm_verity_status'] != 0:
        raise ValueError('Unexpected resulting state')
    sectors = sorted({n // 512 * 512 for n in changes})
    report = dict(info, candidate_sha256=sha(result), changed_bytes=len(changes),
                  allowed_ranges=allowed, flash_writes_performed=False,
                  status='dry-run-structural-candidate-not-authenticated',
                  changed_sectors=[{'offset': n, 'length': 512,
                                    'before_sha256': sha(data[n:n + 512]),
                                    'candidate_sha256': sha(result[n:n + 512])}
                                   for n in sectors])
    return result, report


def main():
    parser = argparse.ArgumentParser(description='Offline inspection only; no candidate authentication or device access')
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.capture.read_bytes()), indent=2))


if __name__ == '__main__':
    main()
