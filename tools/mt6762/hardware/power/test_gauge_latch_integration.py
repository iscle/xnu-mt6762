"""Compile actual native probe + actual public PWRAP guard; no hardware I/O."""
from pathlib import Path
import argparse
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = (HERE.parents[3] / 'bsd/dev/mt6762_power.c').read_text()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sanitize', action='store_true', help='Enable host AddressSanitizer and UBSan')
options = parser.parse_args()


def function(name):
    marker = SOURCE.index(name + '(')
    begin = SOURCE.rfind('\n', 0, marker) + 1
    opening = SOURCE.index('{', marker)
    depth, end = 1, opening + 1
    while depth:
        depth += (SOURCE[end] == '{') - (SOURCE[end] == '}')
        end += 1
    text = SOURCE[begin:end] + '\n'
    # The public API's type is on the same line; static functions have their
    # return type on the preceding line in this driver.
    if text.startswith(name + '('):
        text = 'static int ' + text
    return text


with tempfile.TemporaryDirectory(prefix='mt6762-gauge-latch-') as directory:
    temporary = Path(directory)
    (temporary / 'gauge_latch_power_functions.c').write_text(
        function('verified') + function('pwrap_transfer') + function('mt6762_pwrap_write16'))
    binary = temporary / 'probe'
    sanitize = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if options.sanitize else []
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-g', '-I', str(temporary), str(HERE / 'test_gauge_latch_integration.c'),
                    '-o', str(binary)] + sanitize, check=True)
    subprocess.run([str(binary)], check=True)
