#!/usr/bin/env python3
"""Prepare a recovery-partition diagnostic candidate; never contact a device."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import bootimg

STOCK_RECOVERY = '470a453801aefddc83810f7b45647ecd581f1cd93a87ff51ab178561e82c2a15'
AVBTOOL = 'e5a664a38db623da00f080219bc0ee60a640a9dc4a872803616fae4938ac749b'
PARTITION_SIZE = 0x2000000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('diagnostic', 'recovery-backup', 'avbtool', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    backup = args.recovery_backup.read_bytes()
    if len(backup) != PARTITION_SIZE or sha(backup) != STOCK_RECOVERY:
        raise ValueError('Require exact inspected stock recovery backup')
    if sha(args.avbtool.read_bytes()) != AVBTOOL:
        raise ValueError('Require pinned official AOSP avbtool')
    source = args.diagnostic.read_bytes()
    diagnostic, template = bootimg.parse(source), bootimg.parse(backup)
    kernel = bootimg.kernel_gzip_info(diagnostic.parts['kernel'])
    if diagnostic.parts['dtb'] != template.parts['dtb']:
        raise ValueError('Diagnostic/stock recovery base DTB mismatch')
    for name in bootimg.ADDRESS_OFFSETS:
        if diagnostic.address(name) != template.address(name):
            raise ValueError('Diagnostic/stock recovery load address mismatch')
    packed = bootimg.pack(template, diagnostic.parts['kernel'], diagnostic.parts['ramdisk'])
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    image = out/'recovery.img'
    image.write_bytes(packed)
    command = [sys.executable, str(args.avbtool.resolve()), 'add_hash_footer',
               '--image', str(image), '--partition_name', 'recovery',
               '--partition_size', str(PARTITION_SIZE), '--algorithm', 'NONE',
               '--hash_algorithm', 'sha256', '--salt', sha(packed)]
    subprocess.run(command, check=True)
    complete = image.read_bytes()
    result = bootimg.parse(complete)
    if len(complete) != PARTITION_SIZE or complete[:len(packed)] != packed:
        raise ValueError('AVB tooling changed the diagnostic payload')
    for name in ('kernel', 'ramdisk'):
        if result.parts[name] != diagnostic.parts[name]:
            raise ValueError('Embedded diagnostic changed')
    for name in ('dtb', 'recovery_dtbo'):
        if result.parts[name] != template.parts[name]:
            raise ValueError('Stock recovery device tree component changed')
    if result.footer is None or result.footer['original_size'] != len(packed):
        raise ValueError('Invalid AVB footer extent')
    vm = result.footer['vbmeta_offset']
    # AVB algorithm NONE, zero authentication block, zero signature size.
    if complete[vm:vm+4] != b'AVB0' or struct.unpack_from('>Q', complete, vm+12)[0] != 0:
        raise ValueError('Unexpected AVB authentication block')
    if struct.unpack_from('>I', complete, vm+28)[0] != 0:
        raise ValueError('Unexpected AVB algorithm')
    checks = {}
    for action in ('info_image', 'verify_image'):
        check = subprocess.run([sys.executable, str(args.avbtool.resolve()), action,
                                '--image', str(image)], capture_output=True, text=True, check=True)
        (out/(action+'.txt')).write_text(check.stdout+check.stderr)
        checks[action] = sha((check.stdout+check.stderr).encode())
    report = dict(purpose='Recovery-partition diagnostic, not full iOS',
        physical_boot_validated=False, requires_explicit_partition_write_authorization=True,
        writes_device=False, image_sha256=sha(complete), image_bytes=len(complete),
        stock_recovery_sha256=sha(backup), diagnostic_input_sha256=sha(source),
        raw_loader=kernel, diagnostic_kernel_and_pid1_unchanged=True,
        stock_base_dtb_and_recovery_dtbo_preserved=True,
        avb_algorithm='NONE', avb_signature_created=False,
        avb_metadata='Unsigned hash descriptor and footer; integrity check, not trusted signing',
        avbtool_sha256=AVBTOOL, avbtool_commit='761178607206f4cb2af79ed9eec52d8cbd814adb',
        producer_sha256=sha(Path(__file__).read_bytes()),
        bootimg_producer_sha256=sha(Path(bootimg.__file__).read_bytes()),
        commands=[command], check_output_sha256=checks,
        limits=['Requires unlocked bootloader and compatible recovery verification policy.',
                'Emulation does not validate the physical recovery boot path.',
                'Original recovery must be restored and read back after any trial.',
                'No boot, LK, or vendor_boot modification is part of this candidate.'])
    (out/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    (out/'SHA256SUMS').write_text(sha(complete)+'  recovery.img\n')
    print(json.dumps(dict(image=str(image), bytes=len(complete), sha256=sha(complete))))


if __name__ == '__main__':
    main()
