#!/usr/bin/env python3
"""Check original IOKit read-only snapshots across an explicit lab publication gap."""
import argparse
import hashlib
import json
from pathlib import Path
import re

UNKNOWN = ('CurrentCapacity', 'MaxCapacity', 'AppleRawCurrentCapacity',
           'AppleRawMaxCapacity', 'DesignCapacity', 'NominalChargeCapacity',
           'Temperature', 'CycleCount', 'TimeRemaining', 'ExternalChargeCapable',
           'AdapterDetails')
MEASURED = ('BatteryInstalled', 'ExternalConnected', 'AppleRawExternalConnected',
            'IsCharging', 'FullyCharged', 'Voltage', 'Amperage', 'InstantAmperage')
REQUIRED = UNKNOWN + MEASURED + ('MT6762ValidFields', 'MT6762ReportExpired')


def parse(text):
    samples = []
    current = None
    service = None
    for line in text.splitlines():
        match = re.search(r'MT6762_BAT_PROBE iteration=(\d+) readonly=1 status=(\S+) monotonic_ns=(\d+) clock_status=(-?\d+)', line)
        if match:
            current = dict(iteration=int(match[1]), status=int(match[2], 0),
                           monotonic_ns=int(match[3]), clock_status=int(match[4]),
                           services=[], properties={}, sysctls={})
            samples.append(current)
            service = None
        if current is None:
            continue
        match = re.search(r'MT6762_BAT_SERVICE name=(\S+) class=(\S+)', line)
        if match:
            service = dict(name=match[1], class_name=match[2], properties={})
            current['services'].append(service)
        match = re.search(r'MT6762_BAT_SNAPSHOT status=(\S+)', line)
        if match and service is not None:
            service['snapshot_status'] = int(match[1], 0)
        match = re.search(r'MT6762_BAT_PROPERTY (\w+)=(\S+)', line)
        if match and service is not None:
            service['properties'][match[1]] = match[2]
        match = re.search(r'MT6762_BAT_SYSCTL (\w+)=(-?\d+) error=(\d+)', line)
        if match:
            current['sysctls'][match[1]] = dict(value=int(match[2]), error=int(match[3]))
        match = re.search(r'MT6762_BAT_COUNT (\d+)', line)
        if match:
            current['count'] = int(match[1])
    for sample in samples:
        native=[s for s in sample['services'] if s['name']=='MT6762Battery' and s['class_name']=='HakiosBattery']
        if len(native)==1:
            sample['properties']=native[0]['properties']
            sample['snapshot_status']=native[0].get('snapshot_status')
            sample['native_service_found']=True
    return samples


def check(samples, require_current=False):
    errors = []
    complete = [s for s in samples if s.get('count',0) >= 1 and
                s.get('native_service_found') and
                s.get('snapshot_status') == 0 and all(k in s['properties'] for k in REQUIRED)]
    if not complete:
        return ['No complete native battery snapshots'], {}
    for s in complete:
        p = s['properties']
        if s['status'] or s['clock_status'] or not s['monotonic_ns']:
            errors.append(f"Snapshot {s['iteration']} has a registry/clock error")
        for k in UNKNOWN:
            if p[k] != '<absent>':
                errors.append(f"Snapshot {s['iteration']} fabricates unknown {k}: {p[k]}")
    if any(b['monotonic_ns'] <= a['monotonic_ns'] for a, b in zip(complete, complete[1:])):
        errors.append('Snapshot monotonic timestamps do not strictly increase')
    expired = [s for s in complete if s['properties']['MT6762ReportExpired'] == 'bool:1']
    transition_snapshots = [s for s in expired if
        s['properties']['MT6762ValidFields'] != 'sint32:0' or
        any(s['properties'][k] != '<absent>' for k in MEASURED)]
    # Property publication and separate BSD getters can cross a boundary.
    # Require repeated coherent expired snapshots, retain transitions explicitly.
    expired = [s for s in expired if s not in transition_snapshots]
    if len(expired) < 2:
        errors.append('Need at least two complete expired observations')
    def valid(s):
        p = s['properties']
        match = re.fullmatch(r'sint32:(\d+)', p['MT6762ValidFields'])
        mask = int(match[1]) if match else 0
        return (p['MT6762ReportExpired'] == 'bool:0' and mask & 4 and
                p['Voltage'] == 'sint32:4400' and
                (not require_current or (mask & 8 and p['Amperage'] == 'sint32:31' and
                                         p['InstantAmperage'] == 'sint32:31')))
    before = [s for s in complete if expired and s['monotonic_ns'] < expired[0]['monotonic_ns'] and valid(s)]
    after = [s for s in complete if expired and s['monotonic_ns'] > expired[-1]['monotonic_ns'] and valid(s)]
    if not before or not after:
        errors.append('Missing valid original IOKit observation before expiry or after recovery')
    observed = []
    for s in expired:
        v = s['sysctls'].get('mt6762_power_valid', {})
        c = s['sysctls'].get('mt6762_adc_voltage_requests', {})
        if v.get('error') == 0 and v.get('value') == 0 and c.get('error') == 0:
            observed.append((s['iteration'], c['value']))
    if len(observed) < 2 or observed[-1][1] <= observed[0][1]:
        errors.append('No independent BSD validity expiry plus continued ADC acquisition during publication gap')
    witness = dict(complete_snapshots=len(complete), expired_snapshots=len(expired),
                   publication_transition_snapshots=transition_snapshots,
                   before=before[-1] if before else None, expired=expired,
                   recovered=after[0] if after else None,
                   expired_adc_request_observations=observed)
    return errors, witness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-current', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new evidence path')
    data = args.serial.read_bytes()
    errors, witness = check(parse(data.decode(errors='replace')), args.require_current)
    result = dict(synthetic_lab_only=True, physical_hardware_tested=False,
                  serial_sha256=hashlib.sha256(data).hexdigest(),
                  required_gauge_current=args.require_current, passed=not errors,
                  errors=errors, observations=witness)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(passed=not errors, errors=errors)))
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
