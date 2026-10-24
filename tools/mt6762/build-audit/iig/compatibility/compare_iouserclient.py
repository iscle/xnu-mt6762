#!/usr/bin/env python3
"""Read-only single-interface IIG 440/256 comparison; never imports outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ids(text):
    return {name: value.lower() for name, value in re.findall(
        r'^#define\s+(\w+_ID)\s+(0x[0-9a-fA-F]+)ULL\s*$', text, re.M)}


def source_lines(text, needle):
    return [i for i, line in enumerate(text.splitlines(), 1) if needle in line]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--xnu', type=Path, required=True)
    p.add_argument('--sdk', type=Path, required=True)
    p.add_argument('--generated', type=Path, required=True)
    args = p.parse_args()
    paths = {
        'old_header': args.sdk / 'System/Library/Frameworks/Kernel.framework/Headers/DriverKit/IOUserClient.h',
        'new_header': args.generated / 'DriverKit/IOUserClient.h',
        'new_implementation': args.generated / 'DriverKit/IOUserClient.iig.cpp',
        'source_interface': args.xnu / 'iokit/DriverKit/IOUserClient.iig',
        'iorpc_header': args.xnu / 'iokit/IOKit/IORPC.h',
        'arm_types': args.xnu / 'bsd/arm/_types.h',
        'stdint': args.xnu / 'EXTERNAL_HEADERS/stdint.h',
        'old_transport_source': args.xnu / 'iokit/Kernel/IOUserServer.cpp',
    }
    texts = {k: p.read_text() for k, p in paths.items()}
    old, new = ids(texts['old_header']), ids(texts['new_header'])
    cpp = texts['new_implementation']
    invokes = sorted(set(re.findall(r'\bIOUserClient::(\w+_Invoke)\s*\(', cpp)))
    report = dict(format=1, scope='Single genuine diagnostic IIG440 IOUserClient output versus SDK13.3 IIG256 header and xnu8796 source; read-only',
        files={key: dict(path=str(path), sha256=digest(path)) for key, path in paths.items()},
        old_ids=old, new_ids=new, id_count=len(new), all_ids_equal=bool(old and old == new),
        methods_added=sorted(new.keys() - old.keys()), methods_removed=sorted(old.keys() - new.keys()),
        methods_changed=sorted(k for k in new.keys() & old.keys() if new[k] != old[k]),
        wrapper_definitions=invokes,
        transport_version_tokens=sorted(set(re.findall(r'\bkIORPCVersion\w+', cpp))),
        generated_kernel_content_lines=source_lines(cpp, 'kernelContent'),
        old_iorpc_struct=re.search(r'struct IORPC \{.*?\n\};', texts['iorpc_header'], re.S).group(0),
        old_inbound_initializer_lines=source_lines(texts['old_transport_source'], 'IORPC rpc ='),
        known_incompatibility='Generated KERNEL dispatch/Invoke code requires IORPC.kernelContent; current source has only message,reply,sendSize,replySize.',
        full_wire_layout_equivalence_proven=False, generated_code_compiled=False,
        generated_code_imported=False, replay_policy_changed=False,
        original_apple_userspace_modified=False)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
