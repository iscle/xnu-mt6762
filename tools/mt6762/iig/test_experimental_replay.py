#!/usr/bin/env python3
"""Actual pinned-candidate integration tests, without compiling or inventing RPC."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import experimental_legacy_replay as experimental
import replay


class ExperimentalReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[3]
        selected = ('MTK_IIG_INPUTS', 'MTK_IIG_GENERATED', 'MTK_IIG_CANDIDATE',
                    'MTK_IIG_INPUT_SHA256', 'MTK_IIG_GENERATION_SHA256', 'MTK_IIG_CANDIDATE_SHA256')
        if any(name in os.environ for name in selected):
            if not all(os.environ.get(name) for name in selected):
                raise ValueError('actual replay tests require all three artifact paths and their explicit pins')
            cls.inputs, cls.generated, cls.candidate = (Path(os.environ[name]) for name in selected[:3])
            cls.ih, cls.gh, cls.ch = (os.environ[name] for name in selected[3:])
            return
        work = Path(os.environ.get('MTK_WORKSPACE', str(cls.root.parent)))
        cls.inputs = work / 'toolchain/iig-inputs-8796-build21-diagnostic26c'
        cls.generated = work / 'toolchain/iig-generated-diagnostic26c'
        cls.candidate = work / 'toolchain/iig-legacy-candidate26c-2'
        if not all(p.is_dir() for p in (cls.inputs, cls.generated, cls.candidate)):
            raise unittest.SkipTest('actual locally generated candidate unavailable; no synthetic RPC substitute')
        cls.ih = '52f15cab4e8194b2cd5e5195be4f3c4e9dc0b24bc5c077beaa05be7ff4137799'
        cls.gh = 'e7a5ada653deb73c997d22994fc0db0db39aef2268297c3cb6b1a407f9d402cf'
        cls.ch = '7fb212a3a7494bc8e3186d23b83e2e8487e01bf4edc4b35ff22faa23386398de'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.build = self.directory / 'fresh-build'
        self.build.mkdir()
        self.base = (self.root, self.inputs, self.generated, self.ih, self.gh, self.build)
        self.config = (self.base, self.candidate, self.ch)

    def args(self, cls='IODispatchQueue'):
        return ['--def', str(self.root / 'iokit/DriverKit' / (cls + '.iig')),
            '--header', str(self.build / (cls + '.h')), '--impl', str(self.build / (cls + '.iig.cpp')),
            '--framework-name', 'DriverKit', '--', '-I' + str(self.root / 'iokit'),
            '-isysroot', '/existing/SDK', '-x', 'c++', '-std=gnu++1z', '-D__IIG=1',
            '-DDRIVERKIT_PRIVATE=1', '-DPRIVATE_WIFI_ONLY=1', '-DXNU_PLATFORM_iPhoneOS']

    def test_actual_candidate_and_helper_copy(self):
        experimental.run_copy(self.args(), self.config)
        for name in ('IODispatchQueue.h', 'IODispatchQueue.iig.cpp', 'MTKIIGLegacy.h'):
            self.assertEqual((self.build / name).read_bytes(), (self.candidate / 'DriverKit' / name).read_bytes())
        self.assertEqual(len(list(self.build.iterdir())), 3)

    def test_normal_replay_still_refuses_diagnostic(self):
        with self.assertRaisesRegex(ValueError, 'generation provenance/version mismatch'):
            replay.validate(*self.base[:5])

    def test_tampered_candidate_refused_no_output(self):
        local = self.directory / 'candidate'
        shutil.copytree(self.candidate, local)
        with (local / 'DriverKit/IOService.iig.cpp').open('ab') as stream:
            stream.write(b'\n/* tampered */\n')
        with self.assertRaisesRegex(ValueError, 'not exact reviewed transform'):
            experimental.run_copy(self.args(), (self.base, local, self.ch))
        self.assertEqual(list(self.build.iterdir()), [])

    def test_tampered_helper_refused_no_output(self):
        local = self.directory / 'candidate'
        shutil.copytree(self.candidate, local)
        (local / 'DriverKit/MTKIIGLegacy.h').write_bytes(b'changed helper')
        with self.assertRaisesRegex(ValueError, 'helper changed'):
            experimental.run_copy(self.args(), (self.base, local, self.ch))
        self.assertEqual(list(self.build.iterdir()), [])

    def test_old_pin_refused(self):
        with self.assertRaisesRegex(ValueError, 'pinned manifest changed'):
            experimental.validate((self.base, self.candidate, '0' * 64))

    def test_unknown_file_refused(self):
        local = self.directory / 'candidate'
        shutil.copytree(self.candidate, local)
        (local / 'DriverKit/unreviewed.cpp').write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            experimental.validate((self.base, local, self.ch))

    def test_local_call_needs_original_local_evidence(self):
        contents = experimental.validate(self.config)
        with self.assertRaisesRegex(ValueError, 'missing RPC wrapper'):
            replay.check_pair('IODispatchQueue', contents['IODispatchQueue.h'], contents['IODispatchQueue.iig.cpp'])
        source = (self.root / 'iokit/DriverKit/IODispatchQueue.iig').read_bytes()
        replay.check_pair('IODispatchQueue', contents['IODispatchQueue.h'], contents['IODispatchQueue.iig.cpp'], source)
        with self.assertRaisesRegex(ValueError, 'missing RPC wrapper'):
            replay.check_pair('IODispatchQueue', contents['IODispatchQueue.h'], contents['IODispatchQueue.iig.cpp'],
                              source.replace(b') LOCAL;', b') LOCALONLY;'))

    def test_helper_output_symlink_refused_before_copy(self):
        target = self.directory / 'unchanged'
        target.write_bytes(b'keep')
        (self.build / 'MTKIIGLegacy.h').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            experimental.run_copy(self.args(), self.config)
        self.assertEqual(target.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
