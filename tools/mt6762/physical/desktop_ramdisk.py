"""Offline layout checks for the inspected phone's eMMC desktop bootstrap.

These checks do not establish filesystem contents or physical storage readiness.
The runtime loader and kernel still admit the controller/card independently.
"""
import struct

SECTOR_SIZE = 512
USERDATA_START = 0x17f800000 // SECTOR_SIZE
USERDATA_SECTORS = 0x1b9bcf8000 // SECTOR_SIZE
MAX_BOOTSTRAP_BYTES = 32 * 1024 * 1024


def validate_slice(start, count):
    """Constrain an explicit read-only slice to the captured userdata extent."""
    if (start < USERDATA_START or count <= 0 or
            start >= USERDATA_START + USERDATA_SECTORS or
            count > USERDATA_START + USERDATA_SECTORS - start):
        raise ValueError('iOS system slice must fit entirely inside captured userdata')
    return dict(start_sector=start, sector_count=count, sector_size=SECTOR_SIZE,
                read_only=True, physical_contents_verified=False)


def validate_bootstrap(data):
    """Check a bounded raw APFS container and its first NXSB checksum only."""
    if not 4096 <= len(data) <= MAX_BOOTSTRAP_BYTES or len(data) % 4096:
        raise ValueError('bootstrap must be a raw APFS image of 4KiB..32MiB')
    magic, block_size, blocks = struct.unpack_from('<4sIQ', data, 32)
    if magic != b'NXSB' or block_size != 4096 or blocks * block_size != len(data):
        raise ValueError('bootstrap APFS container geometry does not match its bytes')
    # Fletcher-64 covers the object after its eight-byte checksum field.
    first = second = 0
    for word, in struct.iter_unpack('<I', data[8:block_size]):
        first = (first + word) % 0xffffffff
        second = (second + first) % 0xffffffff
    low = 0xffffffff - ((first + second) % 0xffffffff)
    high = 0xffffffff - ((first + low) % 0xffffffff)
    if struct.unpack_from('<Q', data)[0] != (high << 32) | low:
        raise ValueError('bootstrap APFS superblock checksum failed')
    return dict(format='raw-apfs', bytes=len(data), block_size=block_size,
                block_count=blocks, nxsb_checksum_verified=True,
                filesystem_contents_verified=False)
