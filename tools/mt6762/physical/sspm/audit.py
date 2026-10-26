#!/usr/bin/env python3
"""Reproduce offline guard tests and record source/linked-fixture provenance."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from probe_fixture import HERE, Program, Machine, ADDRESSES, EXTERNAL, IDENTITY
from test_probe import ProbeTests
from decode import decode


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProbeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit('Guard tests failed; no successful evidence produced.')
    root = HERE.parents[3]
    paths = sorted(HERE.glob('*.py')) + sorted(HERE.glob('*.S')) + sorted(HERE.glob('*.c'))
    paths += [HERE / name for name in ('probe.h', 'fixture.ld', 'README.rst')]
    paths += [HERE.parent / name for name in ('start.S', 'loader.c', 'loader.ld',
                  'SSPM-GUARDED-PROBE-DESIGN.rst', 'sspm-guarded-probe-design-evidence.json')]
    with tempfile.TemporaryDirectory(prefix='sspm-guard-audit-') as directory:
        program = Program(directory)
        complete = Machine(program).run()
        fault = Machine(program, fault_at=12).run()
        symbols = {name: hex(program.symbols[name]) for name in
            ('image_start', 'image_end', 'fixture_record', 'fixture_identity',
             'physical_vectors', 'sspm_probe_vectors', 'sspm_guard_read',
             'sspm_guard_load', 'sspm_guard_after_load', 'sspm_guard_failed',
             'sspm_guard_sync', 'sspm_guard_context', '__stack_start', '__stack_end')}
        reports = {}
        for name, machine in (('all_zero', complete), ('abort_at_out_irq', fault)):
            reports[name] = decode(machine.record(), IDENTITY,
                program.symbols['sspm_guard_load'], program.symbols['physical_vectors'])
        evidence = {
            'schema': 'mt6762-sspm-guard-offline-validation-v1',
            'prototype_origin': 'old xnu checkpoint 2d16066b',
            'production_integrated': False, 'hardware_operations': False,
            'kernel_or_kernel_header_changes': False,
            'test_groups_passed': result.testsRun,
            'source_sha256': {str(p.relative_to(root)): digest(p) for p in paths},
            'dependencies': {name: importlib.metadata.version(name)
                             for name in ('unicorn', 'capstone', 'pyelftools')},
            'compiler': subprocess.check_output([program.command[0], '--version'], text=True).strip(),
            'compile_link_command': [arg.replace(directory, '$TEMP') for arg in program.command],
            'linked_fixture_sha256': program.sha256, 'fixture_symbols': symbols,
            'fixture_identity_hex': IDENTITY.hex(),
            'protected_addresses': [hex(a) for a in ADDRESSES],
            'external_addresses': [hex(a) for a in EXTERNAL],
            'completed_fixture_reads': len(complete.device_reads),
            'completed_fixture_instructions': complete.instruction_count,
            'completed_fixture_max_stack_bytes': complete.initial_sp-complete.minimum_sp,
            'abort_fixture_max_stack_bytes': fault.initial_sp-fault.minimum_sp,
            'bug_fixed': 'Reject destinations overlapping the future 256-byte exception frame, in addition to the 288-byte wrapper frame.',
            'modeled': ['EL1 exception entry', 'ERET', 'system registers', 'counter', 'barriers'],
            'not_established': ['physical bus completion or permission', 'RAZ versus genuine zero',
                'SSPM firmware identity/liveness/preservation', 'mailbox/clock/PMIC ownership',
                'interconnect hang, asynchronous SError or EL2/EL3 containment'],
            'reports': reports,
        }
        args.output.write_text(json.dumps(evidence, indent=2)+'\n')
    print(args.output)


if __name__ == '__main__':
    main()
