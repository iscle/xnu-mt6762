"""Retain source, capture and executed host-test evidence; no device access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
XNU = HERE.parents[3]
PORT = XNU.parents[2] if XNU.parent.name == 'xnu-src' else XNU.parent
CAPTURES = {
    33: '73275964fb858aea490204611b4de11ee019ac02a18192ec5461b0219aa3e9d4',
    34: '21ffa3ebfc4a6598d604ad24042bb89a5f8a9272bc376df60e21974f41e141d7',
    35: 'ee4ebd4740ec810f3a5b5170e9a9c56849d1a375b0cdcae28adb89ac274afa0d',
    36: '84237acde964d7bd4d39b96f5f3375139e160fad2291717596c675b1d505711e',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(source, name):
    begin = source.index(name + '(')
    begin = source.rfind('\n', 0, begin) + 1
    opening = source.index('{', begin)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=Path, default=PORT)
    parser.add_argument('--output', type=Path, default=HERE / 'evidence/gauge-latch-review.json')
    parser.add_argument('--sanitize', action='store_true', help='Require available host ASan/UBSan runtimes')
    args = parser.parse_args()
    unchanged = {
        'bsd/dev/mt6762_gauge_protocol.h': '0561a82b2071e407f612d9949ddb1b29cb546cde2462356b03ba1f58a286fb96',
        'bsd/dev/mt6762_power_protocol.h': '2488c25e65d224d925da65a6156f2fcd2988ebe27413f43b0d8b94445a69df10',
    }
    for name, expected in unchanged.items():
        assert digest(XNU / name) == expected, name
    public_hashes = {
        'pwrap_transfer': '8a519f0732c7f47f57b889f3e3c03ab65e8c33b1a5af6bb69c2f2aa624d62145',
        'mt6762_pwrap_write16': 'a9989800203fd11e1a0db4689a40378f86a00edd5a9d6a347509425b764c1c35',
        'mt6762_pwrap_read16': '0b1d4ccc6c77d26e96195df004de900a9170f7cdf4279f0f09806de9d9f703cd',
    }
    source = (XNU / 'bsd/dev/mt6762_power.c').read_text()
    for name, expected in public_hashes.items():
        assert hashlib.sha256(function(source, name).encode()).hexdigest() == expected, name
    files = [XNU / 'bsd/dev/mt6762_power.c', XNU / 'bsd/dev/mt6762_gauge_latch_probe.c']
    files += [XNU / name for name in unchanged]
    files += [HERE / name for name in ['mt6762_pmic_entry.h', 'mt6762_gauge_probe.h',
        'test_gauge_probe.c', 'test_gauge_latch_integration.c', 'test_gauge_latch_integration.py',
        'test_pmic_entry.c', 'test_pmic_entry_integration.py', 'test_gauge_baseline.py', 'test.sh',
        'audit_gauge_latch.py', 'audit_adc_entry.py', 'GAUGE-LATCH-PROBE.rst',
        'evidence/gauge-protocol-disassembly.txt', 'evidence/gauge-baseline-replay.json',
        'evidence/stock-gauge-vectors.json']]
    before = {str(path): digest(path) for path in files}
    captures = []
    expected_regs = [8, 0xc0c, 0xd08, 0xd0a, 0xc8e, 0xc90, 0xd94, 0xd96,
                     0xe08, 0x108a, 0x108e, 0x109e, 0x1236]
    exact = {8: 0x5730, 0xc0c: 4, 0xd08: 0x129, 0xd0a: 0, 0xc8e: 0x416,
             0xc90: 1, 0xd94: 0, 0xd96: 0x416, 0xe08: 5, 0x1236: 0}
    for number, expected in CAPTURES.items():
        directory = args.port / f'hardware/trace-boot-20261025/capture{number}'
        path = directory / 'xnu-log.bin'
        assert digest(path) == expected
        data = path.read_bytes()
        rows = re.findall(rb'MT6762_PMIC_ENTRY pass=(\d+) index=(\d+) address=([0-9a-f]+) value=([0-9a-f]+)', data)
        observed = {}
        for rawpass, rawindex, rawaddress, rawvalue in rows:
            key = int(rawpass), int(rawindex), int(rawaddress, 16)
            observed.setdefault(key, set()).add(int(rawvalue, 16))
        assert len(observed) == 26
        for passno in range(2):
            for index, address in enumerate(expected_regs):
                values = observed[passno, index, address]
                assert len(values) == 1
                if address in exact:
                    assert values == {exact[address]}
        assert b'MT6762_ADC_ENTRY' not in data and b'MT6762_GAUGE_LATCH_' not in data
        trace = json.loads((directory / 'trace-result.json').read_text())
        captures.append(dict(capture=number, log_path=str(path), log_sha256=expected,
            log_bytes=len(data), raw_record_count=len(rows), deduplicated_records=26,
            trace_result_sha256=digest(directory / 'trace-result.json'),
            trace_sha256=trace['trace_sha256'], retention_proven=trace['retention_proven'],
            pmic_records=[dict(pass_number=p, index=i, address=f'{a:04x}', value=f'{next(iter(v)):04x}')
                          for (p, i, a), v in sorted(observed.items())],
            additional_adc_record_present=False, gauge_latch_record_present=False,
            adc_measurement_fresh=False))
    tests = []
    with tempfile.TemporaryDirectory(prefix='mt6762-gauge-audit-') as temporary:
        for name in ['test_gauge_probe', 'test_pmic_entry']:
            binary = Path(temporary) / name
            command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-g',
                       str(HERE / (name + '.c')), '-o', str(binary)]
            subprocess.run(command, check=True)
            result = subprocess.run([str(binary)], check=True, text=True, capture_output=True)
            tests.append(dict(test=name, compile_command=command, stdout=result.stdout, result='PASS'))
        for name, flags in [('test_gauge_latch_integration.py', ['--sanitize'] if args.sanitize else []),
                            ('test_pmic_entry_integration.py', []), ('test_gauge_baseline.py', [])]:
            command = [sys.executable, str(HERE / name)] + flags
            result = subprocess.run(command, check=True, text=True, capture_output=True)
            tests.append(dict(test=name, command=command, stdout=result.stdout,
                              stderr=result.stderr, result='PASS'))
    assert all(digest(Path(path)) == value for path, value in before.items())
    report = dict(schema='mt6762-hakios-finite-gauge-review-v1', result='PASS',
        source_inputs_stable=True, input_sha256=before, unchanged_protocol_sha256=unchanged,
        unchanged_public_pwrap_function_sha256=public_hashes, capture_context=captures,
        executed_host_tests=tests,
        host_sanitizers_executed=args.sanitize,
        policy=dict(opt_in='fgauge-latch-probe=1', samples=2, maximum_attempted_writes=8,
                    write_address='0d0a', write_sequence_per_sample=['0001','0009','0008','0000'],
                    acquisition_lease_ms=2000, minimum_sample_separation_ms=1000,
                    retry_count=0, speculative_cleanup_writes=0,
                    baseline_rfg=100, baseline_car_tune=1000,
                    public_pwrap_writes_allowed=False, battery_measurement_published=False,
                    adc_request_allowed=False, charge_enable_allowed=False),
        physical_new_probe_executed=False, kernel_built=False, device_accessed=False,
        limitations=['Host MMIO/clock/mutex fixtures do not prove physical firmware exclusion',
                     'Capture33-36 raw ADC values are stale without requested conversion',
                     'No absolute calibration, capacity/SOC or charging policy is established',
                     'An uncertain failed latch remains untouched until parent-controlled recovery'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: pinned captures33-36, unchanged protocols/public PWRAP, executed finite/ADC/baseline tests; no hardware')


if __name__ == '__main__':
    main()
