#!/usr/bin/env python3
"""Fingerprint checked-in and new kernel inputs, excluding generated outputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def snapshot(root):
    names = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']
    ).decode().split('\0')
    source_dirs = {'bsd', 'config', 'iokit', 'libkdd', 'libkern', 'libsa',
                   'libsyscall', 'makedefs', 'osfmk', 'pexpert', 'san',
                   'security', 'EXTERNAL_HEADERS', 'SETUP'}
    files = {}
    for name in sorted(set(names)):
        path = Path(name)
        # Native drivers also include small shared, host-testable protocol headers.
        if not name or not (path.parts[0] in source_dirs or name == 'Makefile' or
                            (name.startswith('tools/mt6762/hardware/') and path.suffix == '.h')):
            continue
        full = root / path
        if full.is_file():
            files[name] = hashlib.sha256(full.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'format': 1, 'sha256': digest, 'files': files}


if __name__ == '__main__':
    root, output = map(Path, sys.argv[1:])
    output.write_text(json.dumps(snapshot(root), indent=2) + '\n')
