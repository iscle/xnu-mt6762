#!/usr/bin/env python3
"""Create a new small deterministic raw file for the read-only MSDC lab.

Never accepts an existing destination. No firmware, private device data or
filesystem is included. The QEMU backend must read these actual file bytes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct


def fnv1a(data):
    result = 2166136261
    for value in data:
        result = ((result ^ value) * 16777619) & 0xffffffff
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--sectors', type=int, default=128)
    args = parser.parse_args()
    if not 3 <= args.sectors <= 8192:
        parser.error('Choose3..8192 sectors for a small explicit fixture')
    path = args.image.absolute()
    metadata = path.with_name(path.name + '.json')
    if path.exists() or path.is_symlink() or metadata.exists() or metadata.is_symlink():
        parser.error('Image or metadata already exists; choose new paths')
    selected = {0, 1, args.sectors - 1}
    records = []
    digest = hashlib.sha256()
    with path.open('xb') as output:
        for lba in range(args.sectors):
            block = bytearray((lba * 29 + i * 17 + (i >> 3)) & 255 for i in range(512))
            magic = b'MT6762_READ_ONLY_LAB\0'
            block[:len(magic)] = magic
            struct.pack_into('<Q', block, 24, lba)
            assert len(block) == 512
            output.write(block)
            digest.update(block)
            if lba in selected:
                records.append(dict(lba=lba, bytes=512, fnv1a32=fnv1a(block),
                                    sha256=hashlib.sha256(block).hexdigest()))
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o444)
    report = dict(synthetic_only=True, firmware_bytes_included=False,
                  image=str(path), sector_size=512, sector_count=args.sectors,
                  image_sha256=digest.hexdigest(), sample_sectors=records)
    with metadata.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
