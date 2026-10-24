import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('iig_snapshot', Path(__file__).with_name('iig_snapshot.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuildIdentity(unittest.TestCase):
    def test_imported_source_change_invalidates_build_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ['experimental_legacy_replay.py', 'replay.py', 'legacy_transform.py',
                     'legacy440_profile.json', 'MTKIIGLegacy.h']
            for name in names:
                (root / name).write_text('original')
            with patch.dict(os.environ, {}, clear=True):
                before = module.snapshot(str(root / names[0]))
                self.assertEqual(len(before['files']), 5)
                for name in names[1:]:
                    (root / name).write_text('changed')
                    self.assertNotEqual(before['sha256'], module.snapshot(str(root / names[0]))['sha256'])
                    (root / name).write_text('original')

    def test_external_artifact_change_invalidates_build_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'generator'
            exe.write_text('tool')
            candidate = root / 'candidate'
            candidate.mkdir()
            artifact = candidate / 'Class.iig.cpp'
            artifact.write_text('original')
            with patch.dict(os.environ, {'MTK_IIG_CANDIDATE': str(candidate)}, clear=True):
                before = module.snapshot(str(exe))
                artifact.write_text('changed')
                self.assertNotEqual(before['sha256'], module.snapshot(str(exe))['sha256'])


if __name__ == '__main__':
    unittest.main()
