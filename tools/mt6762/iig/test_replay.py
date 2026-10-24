#!/usr/bin/env python3
"""Guard/selection tests only. These do not synthesize or validate genuine RPC."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import replay

FLAGS = ['-I/source/iokit', '-isysroot', '/SDK', '-x', 'c++', '-std=gnu++1z',
    '-D__IIG=1', '-DDRIVERKIT_PRIVATE=1', '-DPRIVATE_WIFI_ONLY=1', '-DXNU_PLATFORM_iPhoneOS']


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'xnu'
        self.bundle = self.base / 'inputs'
        self.output = self.base / 'generated'
        self.build = self.root / 'BUILD'
        self.build.mkdir(parents=True)
        self.output.mkdir()
        for name in replay.EXTRA_INPUTS | {'iokit/DriverKit/' + c + '.iig' for c in replay.CLASSES} | {'bsd/sys/test.h'}:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('22.5.0\n' if name == 'config/MasterVersion' else 'test input only\n')
            target = self.bundle / 'source' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
        (self.bundle / 'workflow.py').write_text('# test producer identity; never executed\n')
        self.manifest = dict(format=1, classes=replay.CLASSES, kernel_version='22.5.0',
            upstream_tag='xnu-8796.121.2', platform='iPhoneOS', purpose='code-generation-only',
            contains_sdk=False, contains_binaries=False,
            source_sha256={p: replay.sha((self.root / p).read_bytes()) for p in replay.inventory(self.root)},
            workflow_sha256=replay.sha((self.bundle / 'workflow.py').read_bytes()))
        self.save_manifest()

    def save_manifest(self):
        p = self.bundle / 'inputs.json'
        p.write_text(json.dumps(self.manifest))
        self.ih = replay.sha(p.read_bytes())

    def args(self, cls='OSObject'):
        return ['--def', str(self.root / 'iokit/DriverKit' / (cls + '.iig')),
            '--header', str(self.build / (cls + '.h')), '--impl', str(self.build / (cls + '.iig.cpp')),
            '--framework-name', 'DriverKit', '--'] + FLAGS

    def test_current_inputs(self):
        replay.check_inputs(self.root, self.bundle, self.ih)

    def test_old_source_refused(self):
        (self.root / 'bsd/sys/test.h').write_text('new source\n')
        with self.assertRaisesRegex(ValueError, 'input changed'):
            replay.check_inputs(self.root, self.bundle, self.ih)

    def test_new_relevant_header_refused(self):
        (self.root / 'bsd/sys/new.h').write_text('new header\n')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            replay.check_inputs(self.root, self.bundle, self.ih)

    def test_removed_input_from_manifest_refused(self):
        self.manifest['source_sha256'].pop('bsd/sys/test.h')
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            replay.check_inputs(self.root, self.bundle, self.ih)

    def test_tampered_bundle_refused(self):
        (self.bundle / 'source/bsd/sys/test.h').write_text('tampered\n')
        with self.assertRaisesRegex(ValueError, 'input changed'):
            replay.check_inputs(self.root, self.bundle, self.ih)

    def test_manifest_pin_refused(self):
        (self.bundle / 'inputs.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'pinned manifest'):
            replay.check_inputs(self.root, self.bundle, self.ih)

    def test_duplicate_json_refused(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            replay.load_json('{"format":1,"format":1}')

    def test_escaping_and_symlink_inputs_refused(self):
        for name in ('../outside', '/etc/passwd', 'bsd//test.h', 'bsd/./test.h'):
            with self.assertRaises(ValueError):
                replay.checked_file(self.root, name)
        p = self.root / 'bsd/sys/test.h'
        p.unlink()
        p.symlink_to(self.bundle / 'source/bsd/sys/test.h')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            replay.check_inputs(self.root, self.bundle, self.ih)

    def test_exact_pair_selection(self):
        for cls in replay.CLASSES:
            args, got, flags = replay.parse_invocation(self.args(cls))
            self.assertEqual(got, cls)
            replay.check_flags(flags)
            self.assertEqual(Path(args.impl).name, cls + '.iig.cpp')

    def test_cross_class_pair_refused(self):
        args = self.args()
        args[args.index('--impl') + 1] = str(self.build / 'IOService.iig.cpp')
        with self.assertRaisesRegex(ValueError, 'pair mismatch'):
            replay.parse_invocation(args)

    def test_semantic_flags_refused(self):
        for extra in ('-DKERNEL=1', '-DXNU_PLATFORM_MacOSX', '-DDRIVERKIT_PRIVATE=0', '-include/other.h'):
            with self.assertRaises(ValueError):
                replay.check_flags(FLAGS + [extra])
        with self.assertRaises(ValueError):
            replay.check_flags([x for x in FLAGS if x != '-D__IIG=1'])

    def test_old_generator_and_unsigned_provenance_refused(self):
        for version, signature in [('Xcode 26.6', {}), ('Xcode 15.4', {})]:
            report = dict(format=1, status=replay.STATUS, classes=replay.CLASSES,
                code_generation_only=True, inputs_sha256=self.ih, platform='iPhoneOS',
                xcode_version=version, iig_codesign=signature)
            path = self.output / 'generation.json'
            path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                replay.validate(self.root, self.bundle, self.output, self.ih, replay.sha(path.read_bytes()))

    def test_tampered_output_hash_refused_before_structure(self):
        developer = '/Xcode.app/Contents/Developer'
        tool = developer + '/Toolchains/XcodeDefault.xctoolchain/usr/bin/iig'
        sdk = developer + '/SDK'
        commands = [['/bin/sh', '/bundle/source/bsd/sys/make_posix_availability.sh',
                     '/output/support/bsd/sys/_posix_availability.h'],
                    ['/bin/bash', '/bundle/source/bsd/sys/make_symbol_aliasing.sh', sdk,
                     '/output/support/bsd/sys/_symbol_aliasing.h']]
        for cls in replay.CLASSES:
            flags = [sdk if f == '/SDK' else f for f in FLAGS]
            commands.append([tool, '--def', '/bundle/source/iokit/DriverKit/' + cls + '.iig',
                '--header', '/output/DriverKit/' + cls + '.h', '--impl',
                '/output/DriverKit/' + cls + '.iig.cpp', '--framework-name', 'DriverKit', '--'] + flags)
        outputs = self.output / 'DriverKit'
        outputs.mkdir()
        hashes = {}
        for cls in replay.CLASSES:
            for suffix in ('.h', '.iig.cpp'):
                name = cls + suffix
                (outputs / name).write_bytes(b'tampered bytes; not RPC')
                hashes[name] = '0' * 64
        signature = ['/usr/bin/codesign', '--verify', '--strict', '-R=anchor apple', tool]
        commands = [signature, ['/usr/bin/codesign', '-d', '--verbose=4', tool]] + commands
        report = dict(format=1, status=replay.STATUS, classes=replay.CLASSES,
            code_generation_only=True, inputs_sha256=self.ih, platform='iPhoneOS',
            xcode_version='Xcode 15.4', developer_dir=developer, iig_path=tool, sdk=sdk, alias_sdk=sdk,
            iig_sha256='1' * 64, availability_sha256='2' * 64,
            iig_codesign=dict(verified=True, apple_anchor=True, command=signature), commands=commands, outputs=hashes)
        path = self.output / 'generation.json'
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'output hash mismatch'):
            replay.validate(self.root, self.bundle, self.output, self.ih, replay.sha(path.read_bytes()))
        # Even a reviewed manifest may not change the deployment flags silently.
        report['commands'][-1][-1] = '-DXNU_PLATFORM_MacOSX'
        with self.assertRaises(ValueError):
            replay.check_generation_commands(report)

    def test_known_shim_and_incompatible_struct_refused(self):
        for marker in ('iig shim', '__iig_stub_', 'gen-iig-stubs.py', 'kernelContent'):
            with self.assertRaisesRegex(ValueError, 'shim/empty/incompatible'):
                replay.check_pair('OSObject', ('/* ' + marker + ' */' + ' ' * 300).encode(), b' ' * 300)
        with self.assertRaises(ValueError):
            replay.check_pair('OSObject', b'', b'')

    def test_comment_only_rpc_refused(self):
        with self.assertRaisesRegex(ValueError, 'missing generated RPC'):
            replay.check_pair('OSObject', b'/* IORPC Fake_Invoke() */' + b' ' * 300,
                b'/* IORPC */' + b' ' * 300)

    def test_failed_validation_does_not_touch_output(self):
        h = self.build / 'OSObject.h'
        h.write_text('previous tested header')
        config = (self.root, self.bundle, self.output, self.ih, '0' * 64, self.build)
        with self.assertRaises(ValueError):
            replay.replay(self.args(), config)
        self.assertEqual(h.read_text(), 'previous tested header')
        self.assertFalse((self.build / 'OSObject.iig.cpp').exists())

    def test_copy_selection_with_explicit_mock_not_rpc(self):
        # Transport test only; the genuine-output validator is mocked deliberately.
        # These opaque byte strings are never represented as generated RPC sources.
        payload = {'OSObject.h': b'opaque header transport bytes',
                   'OSObject.iig.cpp': b'opaque implementation transport bytes'}
        config = (self.root, self.bundle, self.output, self.ih, '0' * 64, self.build)
        with patch.object(replay, 'validate', return_value=payload):
            replay.replay(self.args(), config)
        for name, content in payload.items():
            self.assertEqual((self.build / name).read_bytes(), content)

    def test_output_symlink_and_source_destination_refused(self):
        target = self.root / 'bsd/sys/test.h'
        (self.build / 'OSObject.h').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            replay.safe_destination(self.build, self.build / 'OSObject.h')
        for destination in (target, self.build / '../bsd/sys/test.h'):
            with self.assertRaisesRegex(ValueError, 'outside'):
                replay.safe_destination(self.build, destination)


if __name__ == '__main__':
    unittest.main()
