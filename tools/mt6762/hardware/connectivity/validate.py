#!/usr/bin/env python3
"""Offline artifact checks and project passive-record decoder; no device IO.

Structural C parser success is separate from exact stock SHA-256 identity.
No path can grant CONN MMIO, power, firmware, DMA or radio operation permission.
"""
import argparse
import ctypes as C
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ERRORS = ['ok', 'size', 'format', 'range', 'duplicate']
POWERS = ['unknown', 'off', 'transition', 'isolated', 'power-bits-ready-only']

class Region(C.Structure):
    _fields_ = [(x, C.c_uint32) for x in ['offset', 'length', 'device_address', 'feature']]
class Image(C.Structure):
    _fields_ = [(x, C.c_uint32) for x in ['kind', 'payload_bytes', 'region_count', 'chip', 'eco', 'format', 'flags', 'hw_version', 'sw_version', 'target', 'image_type', 'own_version', 'peer_version']] + [('regions', Region * 16)]
class State(C.Structure):
    _fields_ = [(x, C.c_uint32) for x in ['seen', 'stable', 'missing', 'power', 'survey_enabled']] + [(x, C.c_uint64) for x in ['begin', 'end', 'hz']]

def compile_core(directory):
    output = Path(directory) / 'conn_decode.so'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c99', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC', '-shared', str(HERE / 'conn_decode.c'), '-o', str(output)], check=True, capture_output=True)
    lib = C.CDLL(str(output))
    lib.conn_image_parse.argtypes = [C.c_void_p, C.c_size_t, C.c_uint, C.POINTER(Image)]
    lib.conn_state_parse.argtypes = [C.c_void_p, C.c_size_t, C.c_uint, C.POINTER(State)]
    lib.conn_register_address.argtypes = [C.c_size_t]
    lib.conn_register_address.restype = C.c_uint64
    lib.conn_register_count.restype = C.c_size_t
    return lib

def structural(lib, data, kind):
    result = Image()
    error = lib.conn_image_parse(data, len(data), kind, C.byref(result))
    if error:
        raise ValueError('structural-' + ERRORS[error])
    return {key: getattr(result, key) for key, _ in Image._fields_ if key != 'regions'} | {
        'regions': [{k: getattr(r, k) for k, _ in Region._fields_} for r in result.regions[:result.region_count]],
        'addresses_are_firmware_device_addresses_not_host_write_targets': True,
        'crc_validation': 'not-implemented; exact full-file SHA-256 required separately'}

def checked_file(lib, path, expected):
    # Bound read even if a caller substitutes a huge/nonregular file.
    if not path.is_file() or path.stat().st_size != expected['bytes']:
        raise ValueError('artifact-size')
    with path.open('rb') as stream:
        data = stream.read(expected['bytes'] + 1)
    if len(data) != expected['bytes']:
        raise ValueError('artifact-size')
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected['sha256']:
        raise ValueError('artifact-sha256')
    details = structural(lib, data, expected['kind']) if expected['kind'] else {}
    return {'bytes': len(data), 'sha256': digest, 'exact_stock_identity': True, 'structure': details}

def make_record(entries, begin=0, end=0, hz=1):
    # Entries: (PA, first, second, width, valid); unknowns are rejected by C.
    header = struct.pack('<8sHHHHIIQQQ', b'MTKCONN1', 1, 48, len(entries), 24,
                         48 + 24 * len(entries), 0, begin, end, hz)
    return header + b''.join(struct.pack('<QIIBBHI', a, x, y, w, v, 0, 0)
                             for a, x, y, w, v in entries)

def decode_record(lib, data, enabled=False):
    result = State()
    error = lib.conn_state_parse(data, len(data), int(enabled), C.byref(result))
    if error:
        raise ValueError('record-' + ERRORS[error])
    d = {k: getattr(result, k) for k, _ in State._fields_}
    d['power_interpretation'] = POWERS[result.power]
    d['missing_addresses'] = [hex(lib.conn_register_address(i)) for i in range(lib.conn_register_count()) if result.missing & (1 << i)]
    d.update(identity_binding='unbound-observations-only', conn_mmio_authorized=False,
             dma_authorized=False, radio_operation_authorized=False,
             unresolved=['live clocks and rails', 'ADIE/ECO', 'cold-start/reset ownership',
                         'EMI/MPU and buffers', 'DMA routing/coherency', 'firmware/calibration compatibility'])
    return d

def capture_observations(lib, path, enabled=False):
    data = path.read_bytes()
    source = json.loads(data)
    allowed = {lib.conn_register_address(i) for i in range(lib.conn_register_count())}
    entries = []
    for entry in source['registers']:
        address = int(entry['address'], 0)
        if address not in allowed:
            continue
        entries.append((address, entry['first'], entry['second'], entry['width'], entry['valid']))
    begins, ends = source['began_ticks'], source['ended_ticks']
    # Both passes are enclosed. No cross-snapshot combining or fabricated zero value.
    record = make_record(entries, min(begins), max(ends), source['counter_hz'])
    return decode_record(lib, record, enabled) | {'source_sha256': hashlib.sha256(data).hexdigest(), 'selected_entries': len(entries)}

def display_observations(path, identity):
    # Reuse the canonical display ABI validator, with external expected identity.
    # Do NOT turn one retained last-pass sample into two stable observations.
    module_path = HERE.parent.parent / 'physical' / 'display_record.py'
    spec = importlib.util.spec_from_file_location('mtk_conn_display_record', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = path.read_bytes()
    observed = module.decode(raw, identity)
    if not observed['accepted'] or 'power' not in observed:
        raise ValueError('display-record-incomplete')
    first, second = observed['power'][:2]
    a, b = bool(first & 2), bool(second & 2)
    return {'source_sha256': hashlib.sha256(raw).hexdigest(),
            'external_identity_matched': True,
            'identity_binding': 'caller-supplied expected loader identity; verify against frozen manifest separately',
            'values': {'0x10006180': first, '0x10006184': second},
            'conn_ack_pair': [a, b],
            'power_interpretation': 'off-at-recorded-sample' if not a and not b else 'on-acks-only' if a and b else 'inconsistent-acks',
            'stability': 'single final pass; no claim of repeated CONN observation',
            'display_control_0x1000630c_is_not_conn_control_0x1000632c': True,
            'conn_mmio_authorized': False, 'dma_authorized': False,
            'radio_operation_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--calibration', type=Path)
    parser.add_argument('--record', type=Path)
    parser.add_argument('--peripherals', type=Path)
    parser.add_argument('--display', type=Path)
    parser.add_argument('--display-identity', help='externally verified expected loader identity, 64 hex characters')
    parser.add_argument('--survey', action='store_true', help='explicitly interpret passive power bits (does not authorize hardware)')
    args = parser.parse_args()
    if bool(args.artifacts) != bool(args.calibration):
        parser.error('--artifacts and --calibration must be provided together')
    if bool(args.display) != bool(args.display_identity):
        parser.error('--display and --display-identity must be supplied together')
    if not (args.artifacts or args.record or args.peripherals or args.display):
        parser.error('provide artifacts or a retained record')
    profile_bytes = (HERE / 'stock-profile.json').read_bytes()
    profile = json.loads(profile_bytes)
    report = {'profile': profile['id'], 'profile_sha256': hashlib.sha256(profile_bytes).hexdigest(), 'phone_access': False, 'hardware_authorized': False}
    try:
        with tempfile.TemporaryDirectory(prefix='mtk-connectivity-') as temp:
            lib = compile_core(temp)
            if args.artifacts:
                report['artifacts'] = {name: checked_file(lib, args.artifacts / name, spec) for name, spec in profile['files'].items()}
                report['calibration'] = checked_file(lib, args.calibration, profile['calibration'])
            if args.record:
                raw = args.record.read_bytes()
                if len(raw) > 48 + 9 * 24:
                    raise ValueError('record-size')
                report['record'] = decode_record(lib, raw, args.survey)
            if args.display:
                report['display'] = display_observations(args.display, bytes.fromhex(args.display_identity))
            if args.peripherals:
                report['peripherals'] = capture_observations(lib, args.peripherals, args.survey)
        report['result'] = 'PASS-offline-validation-only'
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        report['result'] = 'FAIL'
        # Exception must never include source bytes/calibration contents.
        report['error'] = type(error).__name__ if not isinstance(error, ValueError) else str(error)
    print(json.dumps(report, indent=2))
    return 0 if report['result'].startswith('PASS') else 1

if __name__ == '__main__':
    raise SystemExit(main())
