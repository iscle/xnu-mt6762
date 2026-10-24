#!/usr/bin/env python3
"""Record selected IIG build inputs without running a generator or changing them."""
import hashlib
import json
import os
from pathlib import Path
import sys


def snapshot(default_iig):
    selected = {k: v for k, v in sorted(os.environ.items()) if k.startswith('MTK_IIG_')}
    executable = Path(os.environ.get('IIG', default_iig)).resolve(strict=True)
    files = {str(executable): hashlib.sha256(executable.read_bytes()).hexdigest()}
    # The replay command imports these sources. A stable executable alone does
    # not prove cached generated objects match a changed validator/transform.
    if executable.name in ('replay.py', 'experimental_legacy_replay.py'):
        for name in ('replay.py', 'legacy_transform.py', 'legacy440_profile.json', 'MTKIIGLegacy.h'):
            file = executable.parent / name
            files[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
    # Explicit artifact bundles only; never recurse through the checkout/BUILD.
    for key in ('MTK_IIG_INPUTS', 'MTK_IIG_GENERATED', 'MTK_IIG_CANDIDATE'):
        if key not in selected:
            continue
        root = Path(selected[key]).resolve(strict=True)
        for file in sorted(root.rglob('*')):
            if file.is_file() and file.suffix in ('.h', '.cpp', '.iig', '.json', '.py', '.pl'):
                files[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
    record = dict(format=1, executable=str(executable), selected_environment=selected, files=files)
    record['sha256'] = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return record


if __name__ == '__main__':
    default_iig, output = sys.argv[1:]
    Path(output).write_text(json.dumps(snapshot(default_iig), indent=2) + '\n')
