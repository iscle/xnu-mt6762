#!/usr/bin/env python3
"""Host-only guards; does not pretend to run genuine IIG."""
import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("workflow", Path(__file__).with_name("workflow.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class Guards(unittest.TestCase):
    def test_output_exclusive_and_input_escape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = w.new_directory(root / "new")
            with self.assertRaises(ValueError):
                w.new_directory(output)
            (root / "external").write_text("source")
            with self.assertRaises(ValueError):
                w.checked_path(output, "../external")

    def test_structural_outputs_reject_missing_stub_and_new_abi(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for cls in w.CLASSES:
                (root / (cls + ".h")).write_text("// Guard fixture, not generated RPC\nvoid Test_Invoke();\n" + " " * 300)
                (root / (cls + ".iig.cpp")).write_text("// Guard fixture, not generated RPC\nIORPC\nvoid " + cls + "::Test_Invoke() {}\nvoid " + cls + "::Test() {}\n" + " " * 300)
            before = w.inspect_outputs(root)
            self.assertEqual(len(before), 34)
            victim = root / "OSAction.iig.cpp"
            original = victim.read_text()
            for bad in ("/* no DriverKit implementation generated (iig shim) */",
                        original + "__iig_stub_0", original + "kernelContent"):
                victim.write_text(bad)
                with self.assertRaises(ValueError):
                    w.inspect_outputs(root)
            victim.write_text(original)
            victim.write_text(original + "kernelContent")
            self.assertEqual(len(w.inspect_outputs(root, diagnostic=True)), 34)
            victim.write_text(original.replace("OSAction::Test() {}", "OSAction::Test();"))
            with self.assertRaises(ValueError):
                w.inspect_outputs(root, diagnostic=True)
            victim.write_text(original)
            (root / "unexpected.h").touch()
            with self.assertRaises(ValueError):
                w.inspect_outputs(root)

    def test_input_hash_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "source").mkdir()
            (root / "source/example.h").write_text("expected")
            (root / "workflow.py").write_text("test fixture")
            w.write_json(root / "inputs.json", dict(format=1, classes=w.CLASSES,
                kernel_version="22.5.0", platform="iPhoneOS",
                workflow_sha256=w.digest(root / "workflow.py"),
                source_sha256={"example.h":w.digest(root / "source/example.h")}))
            w.verify_inputs(root)
            (root / "source/example.h").write_text("changed")
            with self.assertRaises(ValueError):
                w.verify_inputs(root)

    def test_diagnostic_version_is_explicit_and_bounded(self):
        w.check_xcode_version("Xcode 15.4\nBuild version 15F31d")
        w.check_xcode_version("Xcode 26.6\nBuild version diagnostic", 26)
        for version, mode in (("Xcode 26.6", None), ("Xcode 15.4", 26),
                              ("Xcode 27.0", 26), ("Xcode 26.6", 27)):
            with self.assertRaises(ValueError):
                w.check_xcode_version(version, mode)

    def test_normal_verifier_rejects_diagnostic_before_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w.write_json(root / "generation.json", dict(
                status="diagnostic-generated-not-compatible", classes=w.CLASSES,
                xcode_version="Xcode 26.6", diagnostic_xcode_major=26,
                iig_codesign=dict(verified=True, apple_anchor=True)))
            with mock.patch.object(w, "verify_inputs", return_value={}), \
                    mock.patch.object(w, "inspect_outputs") as inspect:
                with self.assertRaises(ValueError):
                    w.verify(argparse.Namespace(bundle=root, output=root))
                inspect.assert_not_called()

    def test_local_call_requires_original_source_and_declared_wrapper(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(w, "CLASSES", ["GuardClass"]):
            root = Path(td)
            output, source = root / "out", root / "source"
            output.mkdir(); source.mkdir()
            header = "// Guard fixture only\nvoid Create() LOCAL; void Create_Call(); void Create_Invoke();\n" + " " * 300
            impl = "// Guard fixture only\nIORPC\nvoid GuardClass::Create_Call() {}\nvoid GuardClass::Create_Invoke() {}\n" + " " * 300
            hp, cp, sp = output / "GuardClass.h", output / "GuardClass.iig.cpp", source / "GuardClass.iig"
            hp.write_text(header); cp.write_text(impl); sp.write_text("void Create() LOCAL;")
            self.assertEqual(len(w.inspect_outputs(output, source=source)), 2)
            with self.assertRaises(ValueError):
                w.inspect_outputs(output)
            for declaration in ("void Create();", "void Create() LOCALONLY;", "// void Create() LOCAL;"):
                sp.write_text(declaration)
                with self.assertRaises(ValueError):
                    w.inspect_outputs(output, source=source)
            sp.write_text("void Create() LOCAL;")
            hp.write_text(header.replace("void Create_Call();", ""))
            with self.assertRaises(ValueError):
                w.inspect_outputs(output, source=source)
            hp.write_text(header)
            cp.write_text(impl.replace("void GuardClass::Create_Invoke() {}", "void GuardClass::Create_Invoke();"))
            with self.assertRaises(ValueError):
                w.inspect_outputs(output, source=source)


if __name__ == "__main__":
    unittest.main()
