#!/usr/bin/env python3
"""Strict local watchdog-trial decoder. No device access; no reset/retention proof."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct

SIZE = 128
MAGIC = 0x4c414952544b544d
LOG_CAPACITY = 1536 * 1024
SYMBOL = b'_mt6762_trial_record'
FIELDS = ('magic version state seconds attempts flags reserved0 first_feed_ns '
          'last_feed_ns expired_ns log_length_before log_length_after mode length '
          'status nonrst nonrst2 req_mode req_irq').split()
STATES = ('disabled', 'armed', 'expiry-recorded', 'cache-clean-completed')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode_unbound(data):
    """Validate raw structure only. Never attributes an expiry to the current trial."""
    if len(data) != SIZE:
        raise ValueError('require exactly128 bytes')
    words = struct.unpack('<Q6I3Q18I', data)
    r = dict(zip(FIELDS, words))
    if r['magic'] != MAGIC or r['version'] != 1:
        raise ValueError('trial magic/version mismatch')
    if r['state'] not in range(4) or r['reserved0'] or any(words[len(FIELDS):]):
        raise ValueError('unknown state or nonzero reserved fields')
    if r['flags'] & ~3:
        raise ValueError('unknown flags')
    if r['state'] == 0:
        if any(words[3:]):
            raise ValueError('changed disabled record')
    else:
        if not 60 <= r['seconds'] <= 1800:
            raise ValueError('enabled deadline outside60..1800')
        if r['state'] == 1:
            if any(r[k] for k in FIELDS[4:] if k != 'first_feed_ns'):
                raise ValueError('armed record contains expiry-only fields')
        else:
            if not r['attempts'] or not r['flags'] & 1:
                raise ValueError('expiry lacks attempts/concurrency flag')
            first, last, end = (r[k] for k in ('first_feed_ns', 'last_feed_ns', 'expired_ns'))
            if not first <= last <= end or end-first < r['seconds'] * 10**9:
                raise ValueError('inconsistent expiry timestamps')
            if end-last > 10**10 + 1:
                raise ValueError('expiry contradicts existing scheduling-gap guard')
            invalid = any(r[k] > LOG_CAPACITY for k in ('log_length_before', 'log_length_after'))
            if r['state'] == 3 and bool(r['flags'] & 2) != invalid:
                raise ValueError('cache-clean result disagrees with log-length flag')
            # State2 can be observed during the helper's partial metadata update.
            # Its lengths/flag2 are not a completed flush result.
    r.pop('magic');r.pop('reserved0')
    r.update(record_sha256=sha(data), state_name=STATES[r['state']],
             identity_bound=False, expiry_attributed_to_selected_image=False,
             cache_clean_attributed_to_selected_image=False,
             reset_proven=False, dram_retention_guaranteed=False,
             coherent_log_snapshot=False)
    return r


def checked(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError('Mach-O range outside artifact')
    return data[offset:offset+size]


def macho(data, symbol=False):
    magic, cpu, subtype, kind, count, length, _, _ = struct.unpack('<8I', checked(data, 0, 32))
    if (magic, cpu, subtype & 255, kind) != (0xfeedfacf, 0x100000c, 0, 2):
        raise ValueError('require thin arm64 executable')
    commands = checked(data, 32, length)
    pos, segments, sections, symtab = 0, [], [], None
    for _ in range(count):
        cmd, size = struct.unpack('<II', checked(commands, pos, 8))
        if size < 8 or size % 8:
            raise ValueError('invalid load command size')
        c = checked(commands, pos, size)
        if cmd == 0x19:
            _, _, _, va, vs, off, fs, _, prot, ns, _ = struct.unpack('<II16s4Q4I', checked(c, 0, 72))
            if size != 72 + ns * 80 or fs > vs or va + vs > 2**64:
                raise ValueError('invalid segment layout')
            checked(data, off, fs)
            for index in range(ns):
                section_va, section_size = struct.unpack_from('<QQ', c, 72+80*index+32)
                if not va <= section_va <= section_va+section_size <= va+vs:
                    raise ValueError('section outside segment')
                sections.append((section_va, section_size))
            if vs:
                segments.append(dict(vmaddr=va, vmsize=vs, fileoff=off, filesize=fs, prot=prot))
        elif cmd == 2:
            if size != 24 or symtab is not None:
                raise ValueError('invalid/duplicate symbol command')
            symtab = struct.unpack_from('<4I', c, 8)
        pos += size
    if pos != length or not segments:
        raise ValueError('incomplete Mach-O commands')
    if not symbol:
        return segments, None
    if symtab is None:
        raise ValueError('symbol artifact lacks LC_SYMTAB')
    off, count, stroff, strsize = symtab
    names = checked(data, stroff, strsize)
    entries = checked(data, off, count * 16)
    matches = []
    for pos in range(0, len(entries), 16):
        name, typ, section, _, va = struct.unpack_from('<IBBHQ', entries, pos)
        if name >= len(names):
            raise ValueError('invalid symbol string offset')
        end = names.find(b'\0', name)
        if end < 0:
            raise ValueError('unterminated symbol')
        if names[name:end] == SYMBOL:
            if typ & 0xe0:  # Legitimate N_GSYM debug record accompanies the definition.
                continue
            if typ & 0x0e != 0x0e or not 1 <= section <= len(sections):
                raise ValueError('trial symbol is not a defined section symbol')
            start, size = sections[section-1]
            if not start <= va or va+SIZE > start+size:
                raise ValueError('trial record does not fit its defining section')
            matches.append(va)
    if len(matches) != 1:
        raise ValueError('require one defined trial symbol')
    return segments, matches[0]


def decode_bound(data, *, physical_address, kernel_bytes, symbol_bytes,
                 manifest, trace_bytes, binding_bytes, binding_sha256):
    """Bind observations to externally reviewed provenance, not a self-approved flag.

    The caller must pin binding_sha256 independently of the supplied document.
    That reviewed document asserts the stripped/unstripped relationship; this
    function checks both artifact hashes but does not reproduce stripping.
    """
    if not re.fullmatch('[0-9a-f]{64}', binding_sha256) or sha(binding_bytes) != binding_sha256:
        raise ValueError('external binding digest mismatch')
    b = json.loads(binding_bytes)
    keys = {'format', 'kernel_sha256', 'symbol_sha256', 'image_sha256',
            'trace_identity', 'symbol_va', 'physical_address'}
    if not isinstance(b, dict) or set(b) != keys or type(b['format']) is not int or b['format'] != 1:
        raise ValueError('unknown binding schema')
    for k in ('kernel_sha256', 'symbol_sha256', 'image_sha256', 'trace_identity'):
        if not isinstance(b[k], str) or not re.fullmatch('[0-9a-f]{64}', b[k]):
            raise ValueError('malformed binding digest/identity')
    if sha(kernel_bytes) != b['kernel_sha256'] or sha(symbol_bytes) != b['symbol_sha256']:
        raise ValueError('frozen kernel/symbol artifact mismatch')
    if manifest['kernel_sha256'] != b['kernel_sha256'] or manifest['image_sha256'] != b['image_sha256']:
        raise ValueError('selected image differs from reviewed binding')
    if manifest['trace']['identity'] != b['trace_identity']:
        raise ValueError('selected trace identity differs from binding')
    trace_path = Path(__file__).resolve().parents[2] / 'physical/trace_record.py'
    spec = importlib.util.spec_from_file_location('mtk_trial_trace', trace_path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    trace = module.decode(trace_bytes, bytes.fromhex(b['trace_identity']))
    if trace['phase'] != 10 or not trace['executed'] or not trace['ram']:
        raise ValueError('require committed same-image final loader trace')
    segments, _ = macho(kernel_bytes)
    symbol_segments, va = macho(symbol_bytes, symbol=True)
    if any(type(b[k]) is not int for k in ('symbol_va', 'physical_address')) or va != b['symbol_va']:
        raise ValueError('binding symbol VA disagrees with actual symbol artifact')
    if va % 64 or not any(s['prot'] & 2 and s['vmaddr'] <= va and va+SIZE <= s['vmaddr']+s['vmsize'] for s in symbol_segments):
        raise ValueError('symbol outside aligned writable allocation')
    loaded = manifest['segments']
    if len(loaded) != len(segments):
        raise ValueError('manifest load segments disagree with frozen kernel')
    bases, target = set(), []
    for s, m in zip(segments, loaded):
        if any(type(m[k]) is not int or m[k] != s[k] for k in ('vmsize', 'fileoff', 'filesize')):
            raise ValueError('manifest segment does not match frozen kernel')
        offset = m['offset']
        if type(offset) is not int or offset < 0 or offset+s['vmsize'] > 0x18000000:
            raise ValueError('invalid physical loader segment offset')
        bases.add(s['vmaddr']-offset)
        if s['prot'] & 2 and s['vmaddr'] <= va and va+SIZE <= s['vmaddr']+s['vmsize']:
            target.append(trace['ram'] + offset + va-s['vmaddr'])
    if len(bases) != 1 or len(target) != 1 or type(physical_address) is not int or not 0 < physical_address <= 2**64-SIZE:
        raise ValueError('ambiguous or invalid relocation/address')
    if target[0] != physical_address or b['physical_address'] != physical_address:
        raise ValueError('observed address differs from symbol-derived physical address')
    r = decode_unbound(data)
    r.update(identity_bound=True, binding_sha256=binding_sha256,
             kernel_sha256=b['kernel_sha256'], symbol_sha256=b['symbol_sha256'],
             image_sha256=b['image_sha256'], trace_identity=b['trace_identity'],
             symbol_va=hex(va), physical_address=hex(physical_address),
             expiry_attributed_to_selected_image=r['state'] >= 2,
             cache_clean_attributed_to_selected_image=r['state'] == 3,
             strip_equivalence_verified_here=False,
             provenance_authority='externally SHA256-pinned reviewed binding document')
    return r


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('record', type=Path)
    p.add_argument('--unbound', action='store_true')
    for name in ('kernel', 'symbols', 'manifest', 'trace', 'binding'):
        p.add_argument('--'+name, type=Path)
    p.add_argument('--binding-sha256')
    p.add_argument('--physical-address', type=lambda v: int(v, 0))
    a = p.parse_args()
    fields = (a.kernel, a.symbols, a.manifest, a.trace, a.binding, a.binding_sha256, a.physical_address)
    if a.unbound:
        if any(v is not None for v in fields):p.error('--unbound cannot accept partial binding arguments')
        result = decode_unbound(a.record.read_bytes())
    else:
        if any(v is None for v in fields):p.error('provide every binding argument or explicitly select --unbound')
        result = decode_bound(a.record.read_bytes(), physical_address=a.physical_address,
            kernel_bytes=a.kernel.read_bytes(), symbol_bytes=a.symbols.read_bytes(),
            manifest=json.loads(a.manifest.read_text()), trace_bytes=a.trace.read_bytes(),
            binding_bytes=a.binding.read_bytes(), binding_sha256=a.binding_sha256)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
