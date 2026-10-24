"""Dry-run adapter for an already connected, explicitly selected mtkclient DA.

There is intentionally no connect(), writeflash(), unlock(), or apply operation.
SEJ authentication uses hardware register access through the existing DA API;
this is not a claim that live preparation is hardware read-only.
"""
import importlib
import json
import os
from pathlib import Path
import subprocess

from planner import PARTITION_SIZE, build_candidate, inspect, sha

MTK_COMMIT = 'fa97df7df41140e60f215f24eea82cb46faf9ff0'


def checked_seccfg_class(checkout):
    checkout = Path(checkout).resolve(strict=True)
    head = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(checkout), 'diff', 'HEAD', '--name-only'], text=True)
    if head != MTK_COMMIT or dirty:
        raise ValueError('Require reviewed, tracked-clean mtkclient commit')
    module = importlib.import_module('mtkclient.Library.Hardware.seccfg')
    expected = checkout / 'mtkclient/Library/Hardware/seccfg.py'
    if Path(module.__file__).resolve() != expected:
        raise ValueError('Imported seccfg module belongs to another checkout')
    original = subprocess.check_output(['git', '-C', str(checkout), 'show',
                                        MTK_COMMIT + ':mtkclient/Library/Hardware/seccfg.py'])
    if sha(expected.read_bytes()) != sha(original):
        raise ValueError('seccfg source differs from reviewed commit')
    return module.SecCfgV4, {'mtkclient_commit': head, 'seccfg_source_sha256': sha(original)}


def authenticated_candidate(data, hwc, mtk, seccfg_class):
    inspect(data)  # Enforce size/version before imported parser seeks or decrypts.
    parsed = seccfg_class(hwc, mtk)
    if not parsed.parse(data) or parsed.hwtype != 'V4':
        raise ValueError('Existing record must authenticate with observed HW V4 variant')

    def authenticate(header):
        import hashlib
        # Same V4 branch as SecCfgV4.create(), without its lock/status edits.
        output = hwc.sej.sej_sec_cfg_hw_V3(hashlib.sha256(header).digest(),
                                         encrypt=True, legacy=True)
        return bytes(output)

    candidate, report = build_candidate(data, authenticate)
    verified = seccfg_class(hwc, mtk)
    if not verified.parse(candidate) or verified.hwtype != 'V4':
        raise ValueError('Generated record failed independent imported-parser authentication')
    if verified.lock_state != 3 or verified.critical_lock_state != 0:
        raise ValueError('Imported parser reports wrong resulting state')
    report.update(authenticated=True, authentication_variant='V4',
                  status='dry-run-authenticated-not-written')
    return candidate, report


def save_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def prepare_from_connected_mtk(mtk, output_dir, checkout):
    """Read fresh seccfg, authenticate, and save local review artifacts only.

    Pass the configured `mtk` object used by Main/DaHandler, not Main itself.
    Caller owns connection/session lifecycle. No flash-writing API is called.
    """
    seccfg_class, provenance = checked_seccfg_class(checkout)
    if mtk.config.hwcode != 0x766:
        raise ValueError('Require this observed hardware code0x766')
    if mtk.daloader.xft is None:
        raise ValueError('Require existing configured XFLASH extension')
    pagesize = mtk.daloader.daconfig.pagesize
    if pagesize != 512:
        raise ValueError('Unexpected logical sector size')
    entries = mtk.daloader.get_partition_data(parttype='user')
    selected = [p for p in entries if p.name == 'seccfg']
    if len(selected) != 1:
        raise ValueError('Missing or ambiguous seccfg GPT entry')
    part = selected[0]
    start, length = part.sector * pagesize, part.sectors * pagesize
    # Exact known board geometry; no generic or guessed partition fallback.
    if start != 0xf000000 or length != PARTITION_SIZE:
        raise ValueError('Unexpected live seccfg extent')
    for other in entries:
        if other is part:
            continue
        lo, hi = other.sector * pagesize, (other.sector + other.sectors) * pagesize
        if lo < start + length and start < hi:
            raise ValueError('Live GPT overlaps seccfg')
    destination = Path(output_dir)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)

    def fresh_read():
        raw = mtk.daloader.readflash(addr=start, length=length, filename='',
                                     parttype='user', display=False)
        if not isinstance(raw, (bytes, bytearray)) or len(raw) != length:
            raise ValueError('Short/failed seccfg read')
        return bytes(raw)

    original = fresh_read()
    save_private(destination / 'seccfg-fresh.bin', original)
    hwc = mtk.daloader.xft.cryptosetup()
    candidate, report = authenticated_candidate(original, hwc, mtk, seccfg_class)
    if fresh_read() != original:
        raise ValueError('Device snapshot changed during preparation; refuse candidate')
    save_private(destination / 'seccfg-candidate.bin', candidate)
    for sector in report['changed_sectors']:
        offset = sector['offset']
        name = f'candidate-sector-{offset:08x}.bin'
        save_private(destination / name, candidate[offset:offset + 512])
        sector.update(file=name, physical_byte_address=start + offset)
    report.update(provenance, live_partition_start=start, live_partition_length=length,
                  live_reads_equal=True, hardware_crypto_used=True,
                  note='Review artifacts only. No persistent writes, lock changes, or hardware status clearing.')
    save_private(destination / 'report.json', (json.dumps(report, indent=2) + '\n').encode())
    return report
