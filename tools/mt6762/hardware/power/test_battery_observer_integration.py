"""Compile actual inherited battery observer + actual public PWRAP guard; no hardware I/O."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = (HERE.parents[3] / 'bsd/dev/mt6762_power.c').read_text()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sanitize', action='store_true', help='Enable host AddressSanitizer and UBSan')
options = parser.parse_args()


def function(name, source=SOURCE):
    marker = source.index(name + '(')
    begin = source.rfind('\n', 0, marker) + 1
    opening = source.index('{', marker)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    text = source[begin:end] + '\n'
    # The public API's type is on the same line; static functions have their
    # return type on the preceding line in this driver.
    if text.startswith(name + '('):
        text = 'static int ' + text
    return text


with tempfile.TemporaryDirectory(prefix='mt6762-battery-observer-') as directory:
    temporary = Path(directory)
    (temporary / 'battery_observer_power_functions.c').write_text(
        function('verified') + function('pwrap_transfer') + function('mt6762_pwrap_read16') + function('mt6762_pwrap_write16'))
    gauge = (HERE.parents[3] / 'bsd/dev/mt6762_gauge.c').read_text()
    observation = re.search(r'struct gauge_observation \{.*?\n\};', gauge, re.S).group()
    (temporary / 'battery_observer_gauge_getters.c').write_text(observation + '\n' +
        'static int gauge_mutex,valid;\nstatic struct gauge_observation observation;\n' +
        function('observation_read', gauge) + function('mt6762_gauge_current_snapshot', gauge) +
        function('mt6762_gauge_current_read', gauge))
    binary = temporary / 'probe'
    sanitize = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if options.sanitize else []
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-g', '-I', str(temporary), str(HERE / 'test_battery_observer_integration.c'),
                    '-o', str(binary)] + sanitize, check=True)
    subprocess.run([str(binary)], check=True)
