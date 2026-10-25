"""Guarded command-field operations for the reviewed recovery trial.

No connection, reboot, erase, or security-state operation. The caller must own
the DA session, authenticate the unlocked device, check GPT geometry, save the
complete fresh baseline privately, and have user authorization before calling
arm/restore. Any error forbids reset until the caller resolves storage state.
"""
import hashlib

PARA_ADDRESS = 0x2108000
PARA_SIZE = 0x80000
RECOVERY_ADDRESS = 0x108000
RECOVERY_SIZE = 0x2000000
CANDIDATE_SHA256 = 'b57766a667c18e6ba854c81a24346c6582ad02fa31f89a93769c7086275c0005'
COMMAND = b'boot-recovery'.ljust(32, b'\0')
BOOTLOADER_REQUEST = b'bootonce-bootloader'.ljust(32, b'\0')


def baseline_checked(data, *, allow_bootloader_request=False):
    if not isinstance(data, bytes) or len(data) != PARA_SIZE:
        raise ValueError('Require a complete para baseline')
    # Empty C strings; trailing unused bytes are retained for exact restoration.
    reviewed = allow_bootloader_request and data[:32] == BOOTLOADER_REQUEST
    if (data[0] and not reviewed) or data[64]:
        raise ValueError('Existing boot command or recovery arguments require review')
    return data


def arm_image(baseline, *, allow_bootloader_request=False):
    baseline_checked(baseline, allow_bootloader_request=allow_bootloader_request)
    return COMMAND + baseline[32:]


def restore_image(baseline, current, *, allow_bootloader_request=False):
    baseline_checked(baseline, allow_bootloader_request=allow_bootloader_request)
    if not isinstance(current, bytes) or len(current) != PARA_SIZE:
        raise ValueError('Require a complete current para image')
    if current[:32] not in (COMMAND, baseline[:32]):
        raise ValueError('Current boot command belongs to a different operation')
    # Never overwrite status/arguments or unrelated bytes updated since arming.
    return baseline[:32] + current[32:]


def read_exact(io, address, size):
    data = io.read(address, size)
    if not isinstance(data, bytes) or len(data) != size:
        raise IOError('Incomplete device read')
    return data


def write_checked(io, before, after):
    if before[32:] != after[32:]:
        raise ValueError('Operation attempted to change more than the command')
    if before != after and not io.write(PARA_ADDRESS, after[:512]):
        raise IOError('Command-sector write uncertain; do not reset')
    actual = read_exact(io, PARA_ADDRESS, PARA_SIZE)
    if actual != after:
        raise IOError('Full para readback mismatch; do not reset')
    return {'before_sha256': hashlib.sha256(before).hexdigest(),
            'after_sha256': hashlib.sha256(actual).hexdigest(),
            'full_readback_verified': True, 'bytes_after_command_preserved': True,
            'written_bytes': 512 if before != after else 0}


def arm(io, baseline, *, allow_bootloader_request=False):
    target = arm_image(baseline, allow_bootloader_request=allow_bootloader_request)
    recovery = read_exact(io, RECOVERY_ADDRESS, RECOVERY_SIZE)
    if hashlib.sha256(recovery).hexdigest() != CANDIDATE_SHA256:
        raise ValueError('Recovery differs from the verified diagnostic; no marker write')
    current = read_exact(io, PARA_ADDRESS, PARA_SIZE)
    if current != baseline:
        raise ValueError('Para changed since backup; no marker write')
    return write_checked(io, current, target)


def restore(io, baseline, *, allow_bootloader_request=False):
    baseline_checked(baseline, allow_bootloader_request=allow_bootloader_request)
    current = read_exact(io, PARA_ADDRESS, PARA_SIZE)
    return write_checked(io, current, restore_image(baseline, current,
        allow_bootloader_request=allow_bootloader_request))
