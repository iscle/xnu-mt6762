#!/usr/bin/env python3
"""Compile and run the bounded PIO and actual WMT composition fixtures."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    compiler = shlex.split(os.environ.get('CC', 'cc'))
    with tempfile.TemporaryDirectory(prefix='mt6762-btif-') as directory:
        for name, sources in (
            ('pio', ['btif_pio.c', 'test_btif.c']),
            ('wmt', ['btif_pio.c', 'btif_wmt.c',
                     '../connectivity/wmt_protocol.c', 'test_wmt_transport.c']),
        ):
            binary = Path(directory) / name
            subprocess.run(compiler + ['-std=c99', '-O2', '-Wall', '-Wextra', '-Werror'] +
                           [str(HERE / s) for s in sources] + ['-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == '__main__':
    main()
