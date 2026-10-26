#!/usr/bin/env python3
"""Package an explicitly frozen diagnostic for the exact32MiB normal boot slot.

Offline only. No device commands and no changes to the main vbmeta image.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import bootimg
from build_recovery_trial import AVBTOOL, PARTITION_SIZE

STOCK_BOOT = '95f362d6c5e018fb588ce1101a75120157079571e8749e349141a5a906f09296'
DIAGNOSTICS = (
    'f5287195f43aee30e555325290aac890ff899dbe04c12d97e5a259be1a9c0b58', # Image5
    'd484161ced6f942984794005d2ac1f8710e33dff49a1e15e8e7ecfbc0725112a', # Image6: empty LK placeholder
    '8e2858b929ff0f3fb42c261eb891f60a67d6dd0939727e59016e8f0d8d2184c2', # Image7: establish combined EOI
    '27636a723cc0d449d82442260238968aa839b719e8d15dabf7d360353bdd93ef', # Image8: retained display readback
    'df3d9afc328cc1809e1d2e15551bf24ac5a897db6780096a1ed959c0ed5a08f8', # Image9: measured LK menu console
    'f3249887751e115413399f0c94dbe605f67f5bad20714f087c1f36c99c37b74a', # Image10: preserve measured datapath profile
    'b970c02b9d289bc67ee2b006112689ddbca04f22f44a98cac4e8a6e4efd4ff39', # Image12: passive PWM only after display admission
    'ec89cc686596e2ba649684a6c197523b22fd23c7d979d98de7947d83186f7b8d', # Image15: native display/PWM with retained diagnostic log
    '0aab6a6f6333c0f2eed13728b8d77c0696ca6fa1cc1553d232b186dc98075b6e', # Image16: bounded expanded RAM and passive peripheral record
    '79cd2eaa36baea81a3aa3c916417d3dbf7de903f6287a6ed4a6e2a1b7d78b424', # Image18: inherited touch version/DMA probe, watchdog unchanged
    '17d812e16407974f934d56bf3dca63efb66303e82b26790e1ca1d738dc739347', # Image19: touch INFRA mapping fix and bounded LK card metadata
    '77d0183f98f523f3180a811c4b71cc9800af4a1203a4c56d95b87cf5e78393a8', # Image21: retained I2C setup values and read-only LK PWRAP probe
    'c1920f7877a8c48f6e1c1439ffd86681225153c77e02b95794be22406ab06551', # Image23: guarded synchronous LK storage probe, fully passing kernel41 build
    'f96011b960ba669b8a4e001003115ea2eeb0912c3a2db11cfa03a5f697d321f0', # Image24: measured I2C0 readback fix and inherited storage probe
    'b0c0a3368981ee98f7b67e3c0918be3533d9d7ba65760713142d9991aa78c580', # Image25: APFS bootstrap for bounded eMMC iOS slice; physical result pending
    '3da6756329e3e859cdd2d6be3aae22024851f7cc4ccd7cd863937747002958ef', # Image26: kernel43 inherited read-only power/volume probe
    '7a6c42436822cdfee2e778673b4d78ad985d25fe81f7971d97a52a99091ffb9c', # Image27: kernel43 APFS bootstrap with native button probe
    'a3cbd157a204ee106b0b06bc9c6e9a9ff797025cf612eb72f3ca076d63338add', # Image29: kernel45 retained eMMC R1 response plus native keys
    '685c9736bb489386b417de474e6623226a939ad6eac8593bb514bc3aace41a41', # Image30: kernel48 unreadable BUS_WIDTH fix and retained EXT_CSD fields
    '01852a28ad01b009ad2d88ff4ef84e05a7e428d0202dc22d9f7b25c77dcd336e', # Image31: kernel48 APFS desktop bootstrap; card acceptance/system install pending
    'c77e7733ee10a28c6d48af2538b507a92761f057bd605790bf7828f49f3681ff', # Image32: kernel50 CPU rail reads and expanded passive CPU/I2C5 register capture
    '454afd35cb03ba1d6d3de9503a91ed89920690331cfbe80353b824733491c76b', # Image33: kernel50 desktop bootstrap with expanded passive CPU/I2C5 capture
    '423cf35d2332abcc75282ba2314e3d71043e08a996cf85395ee5d1559c2bb22d', # Image34: kernel51 desktop with existing userspace exception/application tracing
    '5cc8787f0dbc7627ce1ba282c237e994a0f7168e7db7837756bc76ed219a080b', # Image35: kernel51, aligned project bootstrap entry after physical SP-alignment fault
    '3947a4012aa6dfbae60fd2b30a0f25abb98bdae8f0741ec957f9a7f358d62c6e', # Image36: kernel52, corrected bootstrap and setup-only inherited I2C5 observation
    'e83d7382f91afc7fdfac9e47c7b631778f47b4497fb792e44ccd37c5c33dfc41', # Image37: kernel52 charger setup-only; restrict syscall logging to project bootstrap
    'c97942ad9a4f452f358bcec91e3100b1b6e180fd290bc040266595af279fd5c6', # Image38: kernel53 passive PMIC/external SSPM state; opt-in300second watchdog trial
    '4861ee010f69f22de4a2d323b2081edf5d8710bb9d7751b2f76cf56a53c370ca', # Image39: kernel54 storage polling/admission fixes and bounded read-only PSC probe
    '3d880b695d22a992555e951df717a3b4b5ad6667d6ed5a52b2c977d49553ce08', # Image40: kernel54, exact live topology admission for first two-core physical trial
    '857bb39916e74a86fa67bf64e6930fe7be896c98570f28384fceaf08e5d36543', # Image41: same kernel54/two cores; bounded1s software wait for inherited eMMC data timeout
    'ada26d13744a70201472725f0c25e506e429fee3db49abd6f28be9dcd11308f5', # Image42: HakiOS kernel56/helper2; existing two-core handoff, first-frame console release
)
VBMETA_FLAGS3 = '2f3fb6474d7ff35ac4c48ab2bef71247ba50de4a94de2474b7d1b60cd6654f51'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_unsigned_boot(complete, packed):
    """Independently check the one bounded SHA256 boot descriptor and bytes."""
    image = bootimg.parse(complete)
    footer = image.footer
    if len(complete) != PARTITION_SIZE or footer is None:
        raise ValueError('Require exact32MiB image and AVB footer')
    if footer['major'] != 1 or footer['minor'] != 0 or footer['original_size'] != len(packed):
        raise ValueError('Wrong AVB footer version/original extent')
    if complete[:len(packed)] != packed:
        raise ValueError('Diagnostic payload changed')
    offset, size = footer['vbmeta_offset'], footer['vbmeta_size']
    if size < 256 or offset % 4096:
        raise ValueError('Invalid vbmeta extent/alignment')
    header = complete[offset:offset + 256]
    auth_size, aux_size = struct.unpack_from('>2Q', header, 12)
    algorithm, = struct.unpack_from('>I', header, 28)
    desc_offset, desc_size = struct.unpack_from('>2Q', header, 96)
    key_offset, key_size, metadata_offset, metadata_size = struct.unpack_from('>4Q', header, 64)
    if (header[:4] != b'AVB0' or struct.unpack_from('>2I', header, 4) != (1, 0) or
            auth_size or algorithm or aux_size % 64 or 256 + aux_size != size or
            any(header[32:64]) or key_size or metadata_size or
            key_offset > aux_size or metadata_offset > aux_size or
            any(header[112:128]) or any(header[176:256])):
        raise ValueError('Unexpected signed/keyed/flagged/unsupported vbmeta header')
    if desc_offset != 0 or not 132 <= desc_size <= aux_size:
        raise ValueError('Invalid descriptor range')
    descriptor = complete[offset + 256:offset + 256 + desc_size]
    tag, following, image_size, algorithm_name, name_size, salt_size, digest_size, flags = struct.unpack_from('>3Q32s4I', descriptor)
    if (tag != 2 or following + 16 != desc_size or image_size != len(packed) or
            algorithm_name != b'sha256'.ljust(32, b'\0') or
            (name_size, salt_size, digest_size, flags) != (4, 32, 32, 0) or
            any(descriptor[72:132])):
        raise ValueError('Unexpected hash descriptor layout/name length/flags')
    if desc_size != ((132 + name_size + salt_size + digest_size + 7) & ~7):
        raise ValueError('Descriptor padding/size mismatch')
    name = descriptor[132:136]
    salt, digest = descriptor[136:168], descriptor[168:200]
    if name != b'boot' or any(descriptor[200:]):
        raise ValueError('Descriptor does not identify only boot')
    if salt != hashlib.sha256(packed).digest() or digest != hashlib.sha256(salt + packed).digest():
        raise ValueError('Boot descriptor salt/digest mismatch')
    if any(complete[len(packed):offset]) or any(complete[offset + 256 + desc_size:offset + size]):
        raise ValueError('Nonzero descriptor or payload alignment padding')
    return dict(partition_name='boot', algorithm='NONE', hash_algorithm='sha256',
                image_size=image_size, salt=salt.hex(), digest=digest.hex(),
                signature_created=False, independently_verified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('diagnostic', 'boot-backup', 'vbmeta-capture', 'avbtool', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    source = args.diagnostic.read_bytes()
    backup = args.boot_backup.read_bytes()
    vbmeta = args.vbmeta_capture.read_bytes()
    if len(backup) != PARTITION_SIZE or sha(backup) != STOCK_BOOT:
        raise ValueError('Require exact complete stock boot backup')
    diagnostic_sha = sha(source)
    if diagnostic_sha not in DIAGNOSTICS:
        raise ValueError('Require an explicitly frozen diagnostic container')
    if (len(vbmeta) != 0x800000 or sha(vbmeta) != VBMETA_FLAGS3 or
            vbmeta[:4] != b'AVB0' or struct.unpack_from('>I', vbmeta, 120)[0] != 3):
        raise ValueError('Require inspected main-vbmeta flags3 capture; never patch it here')
    if sha(args.avbtool.read_bytes()) != AVBTOOL:
        raise ValueError('Require pinned official AOSP avbtool')
    diagnostic, template = bootimg.parse(source), bootimg.parse(backup)
    if any(diagnostic.address(n) != template.address(n) for n in bootimg.ADDRESS_OFFSETS):
        raise ValueError('Load address mismatch')
    if any(diagnostic.parts[n] != template.parts[n] for n in ('second', 'dtb', 'recovery_dtbo')):
        raise ValueError('Non-diagnostic component mismatch')
    packed = bootimg.pack(template, diagnostic.parts['kernel'], diagnostic.parts['ramdisk'])
    if packed != source:
        raise ValueError('Frozen diagnostic is not exact repack of this stock boot header')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    image = out / 'boot.img'
    image.write_bytes(packed)
    command = [sys.executable, str(args.avbtool.resolve()), 'add_hash_footer',
               '--image', str(image), '--partition_name', 'boot',
               '--partition_size', str(PARTITION_SIZE), '--algorithm', 'NONE',
               '--hash_algorithm', 'sha256', '--salt', sha(packed)]
    subprocess.run(command, check=True)
    complete = image.read_bytes()
    avb = validate_unsigned_boot(complete, packed)
    result = bootimg.parse(complete)
    for name in bootimg.PARTS:
        if result.parts[name] != diagnostic.parts[name]:
            raise ValueError('Embedded diagnostic component changed')
    checks = {}
    for action in ('info_image', 'verify_image'):
        check = subprocess.run([sys.executable, str(args.avbtool.resolve()), action,
                                '--image', str(image)], capture_output=True, text=True, check=True)
        text = check.stdout + check.stderr
        (out / (action + '.txt')).write_text(text)
        checks[action] = sha(text.encode())
    if sha(args.boot_backup.read_bytes()) != STOCK_BOOT or sha(args.diagnostic.read_bytes()) != diagnostic_sha or sha(args.vbmeta_capture.read_bytes()) != VBMETA_FLAGS3:
        raise ValueError('Input changed during preparation')
    report = dict(purpose='Normal boot partition XNU payload; userspace identified by source manifest',
        target_partition='boot', image_sha256=sha(complete), image_bytes=len(complete),
        stock_boot_backup_sha256=STOCK_BOOT, stock_boot_backup_bytes=len(backup),
        diagnostic_input_sha256=diagnostic_sha, main_vbmeta_capture_sha256=VBMETA_FLAGS3,
        main_vbmeta_capture_flags=3, main_vbmeta_changed=False,
        main_vbmeta_capture_is_fresh_device_state=False,
        original_diagnostic_components_unchanged=True,
        raw_loader=bootimg.kernel_gzip_info(result.parts['kernel']),
        trace_identity_and_frozen_kernel_unchanged=True,
        avb=avb, avbtool_sha256=AVBTOOL,
        avbtool_commit='761178607206f4cb2af79ed9eec52d8cbd814adb',
        producer_sha256=sha(Path(__file__).read_bytes()),
        bootimg_producer_sha256=sha(Path(bootimg.__file__).read_bytes()),
        commands=[command], check_output_sha256=checks,
        writes_device=False, physical_boot_validated=False,
        limits=['Unsigned descriptor integrity is not a trusted signature.',
                'Require independently confirmed current unlocked state and main-vbmeta flags3.',
                'This exact candidate still requires physical boot validation.',
                'Keep the verified stock boot backup for recovery if needed; no automatic restoration.',
                'No change to recovery, LK, vendor_boot, BCB or main vbmeta is performed by this tool.'])
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(sha(complete) + '  boot.img\n')
    print(json.dumps(dict(image=str(image), size=len(complete), sha256=sha(complete))))


if __name__ == '__main__':
    main()
