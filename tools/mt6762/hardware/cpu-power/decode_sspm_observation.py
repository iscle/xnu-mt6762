#!/usr/bin/env python3
"""Decode the bounded passive SSPM log record; no device access or DVFS grant."""
import argparse
import hashlib
import json
import re
from pathlib import Path

GROUPS = {'guards': (5, 1), 'pvt': (144, 2), 'eem': (3, 4), 'ppm': (2, 8),
          'voltage': (3, 16), 'index': (3, 32), 'vote': (3, 64),
          'mailbox': (9, 128), 'irq': (2, 256)}
HEADER = re.compile(r'MT6762_SSPM_OBSERVE version=1 passes=2 words=174 '
                    r'stable_groups=([0-9a-f]{3}) guards=([01]) '
                    r'c62_representation=([01]) ownership=0 liveness=unknown')
RAW = re.compile(r'MT6762_SSPM_RAW pass=([01]) group=([a-z]+) word=(\d+) '
                 r'count=([1-4]) ((?:[0-9a-f]{8} ){3}[0-9a-f]{8})')
GUARDS = [0x55aa55aa, 0xaa55aa55, 0x55aa55aa, 0xaa55aa55, 0x55aa55aa]


def c62_match(words):
    rows = json.loads((Path(__file__).parent / 'evidence/stock-c62-pvt.json').read_text())['rows']
    for domain in range(3):
        if words[domain*36+32] != 0xffffffff:
            return False
        for i in range(16):
            fv, method = words[domain*36+i], words[domain*36+16+i]
            mhz, _, post, clk = rows[domain*16+i]
            if (fv & 0xf0000000 or ((fv >> 16) & 0xfff) > 127 or
                    method & 0xff00ff00 or fv & 0xffff != mhz or
                    method & 0xff != post or (method >> 16) & 0xff != clk):
                return False
    return True


def decode(blob):
    text = blob.decode('ascii', errors='replace')
    headers = list(HEADER.finditer(text))
    if len(headers) != 1:
        raise ValueError('Expected exactly one version1 complete SSPM observation')
    header = headers[0]
    tail = text[header.end():]
    end = tail.find('MT6762_SSPM_OBSERVE end=1 writes=0')
    if end < 0:
        raise ValueError('Truncated SSPM observation')
    stable = int(header[1], 16)
    if stable & ~511:
        raise ValueError('Unknown stability bits')
    samples = [{name: [None]*count for name, (count, _) in GROUPS.items()}
               for _ in range(1 if stable == 511 else 2)]
    for line in tail[:end].splitlines():
        if 'MT6762_SSPM_RAW' not in line:
            continue
        match = RAW.fullmatch(line.strip())
        if not match:
            raise ValueError('Malformed SSPM raw line')
        p, name, start, count, raw = match.groups()
        p, start, count = int(p), int(start), int(count)
        words = [int(word, 16) for word in raw.split()]
        if p >= len(samples) or name not in GROUPS or start % 4:
            raise ValueError('Unexpected pass/group/word')
        group = samples[p][name]
        if count != min(4, len(group)-start) or any(words[count:]):
            raise ValueError('Unexpected count or nonzero padding')
        if not 0 <= start < len(group) or any(v is not None for v in group[start:start+count]):
            raise ValueError('Duplicate/out-of-range SSPM raw words')
        group[start:start+count] = words[:count]
    if any(v is None for sample in samples for group in sample.values() for v in group):
        raise ValueError('Missing SSPM raw words')
    if len(samples) == 2:
        computed = sum(flag for name, (_, flag) in GROUPS.items() if samples[0][name] == samples[1][name])
        if stable != computed:
            raise ValueError('Raw samples disagree with stability report')
    guards = bool(stable & 1) and samples[0]['guards'] == GUARDS
    c62 = guards and bool(stable & 2) and c62_match(samples[0]['pvt'])
    if guards != bool(int(header[2])) or c62 != bool(int(header[3])):
        raise ValueError('Raw samples disagree with representation report')
    interpretation = []
    for s in samples:
        interpretation.append({
            'pending_platform_cpu_in': s['mailbox'][0] & 3,
            'pending_platform_cpu_out': s['mailbox'][1] & 3,
            'mailbox0_irq_enabled': bool(s['irq'][0] & (1 << 13)),
            'mailbox0_irq_active': bool(s['irq'][1] & (1 << 13)),
            'eem_flags_clear': not any(s['eem']),
            'current_indices_in_range': all(v <= 15 for v in s['index']),
            'ppm_indices_in_range': all((v >> 16) <= (v & 0xffff) <= 15 for v in s['ppm']),
            'vote_fields': [{'index': v & 15, 'counter': (v >> 4) & 255,
                             'upper_bits': v >> 12} for v in s['vote']],
        })
    return {'input_sha256': hashlib.sha256(blob).hexdigest(), 'version': 1,
            'stable_groups': stable, 'matching_second_raw_pass_omitted': len(samples) == 1,
            'guards_match': guards, 'c62_representation_match': c62,
            'samples': samples, 'interpretation': interpretation,
            'ownership_granted': False, 'controller_ready': False,
            'limits': ['Guard/table matches do not prove CPU-DVFS initialization, bin, EEM, freshness or firmware liveness.',
                       'Voltage words have no asserted physical measurement, units or request correlation.',
                       'Votes are submissions, not sequence acknowledgements; snapshots are not atomic or ABA-proof.',
                       'No mailbox status was acknowledged; this observer does not own firmware or IRQs.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(decode(args.log.read_bytes()), indent=2) + '\n')


if __name__ == '__main__':
    main()
