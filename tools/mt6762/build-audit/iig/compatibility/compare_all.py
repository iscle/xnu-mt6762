#!/usr/bin/env python3
"""Compare all published method IDs and retain per-class interface provenance."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def ids(text):
    entries = re.findall(r'^#define\s+(\w+_ID)\s+(0x[0-9a-fA-F]+)ULL\s*$', text, re.M)
    result = {k: v.lower() for k, v in entries}
    if len(result) != len(entries):
        raise ValueError('duplicate method ID declaration')
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('xnu', 'sdk', 'generated', 'output'):
        p.add_argument('--' + arg, type=Path, required=True)
    a = p.parse_args()
    old_root = a.sdk / 'System/Library/Frameworks/Kernel.framework/Headers/DriverKit'
    classes = sorted(path.stem for path in (a.xnu / 'iokit/DriverKit').glob('*.iig'))
    if len(classes) != 17:
        raise ValueError('expected 17 original interfaces')
    rows = []
    for cls in classes:
        old = old_root / (cls + '.h')
        new = a.generated / 'DriverKit' / (cls + '.h')
        impl = a.generated / 'DriverKit' / (cls + '.iig.cpp')
        source = a.xnu / 'iokit/DriverKit' / (cls + '.iig')
        old_text, new_text, cpp = old.read_text(), new.read_text(), impl.read_text()
        previous, current = ids(old_text), ids(new_text)
        rows.append(dict(class_name=cls, old_header_sha256=sha(old), new_header_sha256=sha(new),
            implementation_sha256=sha(impl), source_interface_sha256=sha(source),
            old_generator=old_text.splitlines()[0], new_generator=new_text.splitlines()[0],
            old_ids=previous, new_ids=current, all_ids_equal=bool(previous and previous == current),
            added=sorted(current.keys() - previous.keys()), removed=sorted(previous.keys() - current.keys()),
            changed=sorted(k for k in current.keys() & previous.keys() if current[k] != previous[k]),
            invoke_definitions=sorted(set(re.findall(r'\b' + cls + r'::(\w+_Invoke)\s*\(', cpp))),
            transport_version_tokens=sorted(set(re.findall(r'\bkIORPCVersion\w+', cpp)))))
    result = dict(format=1, scope='All 17 IIG440 diagnostic interfaces versus SDK13.3 generated headers',
        classes=rows, method_id_count=sum(len(r['new_ids']) for r in rows),
        all_method_ids_equal=all(r['all_ids_equal'] for r in rows),
        generation_manifest_sha256=sha(a.generated / 'generation.json'),
        full_wire_layout_equivalence_proven=False,
        limitations=['Old generated implementation/wire-struct definitions are unavailable in the SDK headers.',
            'Method ID agreement does not establish argument offsets, ownership or dispatch behavior.',
            'Compilation, export audit and actual handler execution are separate checks.',
            'No Apple userspace changed or physical hardware tested.'])
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'classes'}, indent=2))
    return int(not result['all_method_ids_equal'])


if __name__ == '__main__':
    raise SystemExit(main())
