"""Bounded, backed-up iOS slice writer; hardware adapters must supply fresh guards.

No device discovery, reset, format, retry or partition-table changes exist here.
The caller must pin the active device, fresh GPT and preserved partition hashes
in guard(). An exception leaves any partial write in place for inspection.
"""
import hashlib
import os
from pathlib import Path

from desktop_ramdisk import SECTOR_SIZE, validate_slice


def identity(stream):
    s = os.fstat(stream.fileno())
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_exact(io, address, size):
    data = io.read(address, size)
    require(isinstance(data, (bytes, bytearray)) and len(data) == size,
            'short or invalid media read; stop without reset')
    return bytes(data)


def install(io, source, backup, expected_sha256, start, count, guard, record,
            chunk_bytes=4*1024*1024):
    """Write one explicit extent after a complete backup; verify every byte.

    io has read(address,size) and write(address,bytes). guard() must raise on
    device/geometry/preserved-partition changes. record(event) persists progress.
    This function never treats a failed write as permission to retry it.
    """
    extent = validate_slice(start, count)
    require(512 <= chunk_bytes <= 4*1024*1024 and chunk_bytes % 512 == 0,
            'invalid bounded transfer size')
    require(len(expected_sha256) == 64 and
            all(c in '0123456789abcdef' for c in expected_sha256), 'invalid source digest')
    size, address = count*SECTOR_SIZE, start*SECTOR_SIZE
    with Path(source).open('rb') as data:
        before = identity(data)
        require(before[2] == size, 'source length differs from slice')
        digest = hashlib.sha256()
        for block in iter(lambda: data.read(chunk_bytes), b''):
            digest.update(block)
        require(identity(data) == before and digest.hexdigest() == expected_sha256,
                'source changed or digest mismatch before media access')
        guard()
        old_hash = hashlib.sha256()
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as saved:
            for offset in range(0, size, chunk_bytes):
                block = read_exact(io, address+offset, min(chunk_bytes,size-offset))
                require(saved.write(block) == len(block), 'short backup write')
                old_hash.update(block)
            saved.flush()
            os.fsync(saved.fileno())
        record(dict(stage='backup_complete', address=address, bytes=size,
                    sha256=old_hash.hexdigest()))
        guard()
        require(identity(data) == before, 'source changed while backing up; no write')
        data.seek(0)
        verified = hashlib.sha256()
        for offset in range(0, size, chunk_bytes):
            require(identity(data) == before, 'source changed during installation; stop')
            block = data.read(min(chunk_bytes,size-offset))
            require(len(block) == min(chunk_bytes,size-offset), 'short source read; stop')
            record(dict(stage='write_begin', address=address+offset, bytes=len(block)))
            require(io.write(address+offset, block) is True,
                    'media write uncertain; stop without retry or reset')
            actual = read_exact(io,address+offset,len(block))
            require(actual == block, 'media readback mismatch; stop without reset')
            verified.update(actual)
            record(dict(stage='chunk_verified', address=address+offset, bytes=len(block)))
        require(identity(data) == before and verified.hexdigest() == expected_sha256,
                'source changed or complete readback digest mismatch; stop')
        guard()
        result = dict(extent, physical_contents_verified=True,
                      source_sha256=expected_sha256, full_readback_sha256=verified.hexdigest(),
                      backup_sha256=old_hash.hexdigest(), bytes_written=size,
                      reset_requested=False, partition_table_written=False)
        record(dict(stage='complete', **result))
        return result
