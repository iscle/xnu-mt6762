#!/usr/bin/env python3
"""Transform guards; actual generated-source tests require the preserved artifact.

No fabricated RPC implementation is used as evidence of ABI compatibility.
Set MTK_IIG_DIAGNOSTIC to a local genuine generated output directory.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("legacy_transform", HERE / "legacy_transform.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


class MetadataGuards(unittest.TestCase):
    def test_profile_inventory(self):
        p = json.loads(t.PROFILE.read_text())
        self.assertEqual(len(p["classes"]), 17)
        self.assertEqual(set(p["files"]), {c + ext for c in p["classes"] for ext in (".h", ".iig.cpp")})
        self.assertEqual(sum(v.get("invocations", 0) for v in p["files"].values()), 94)
        for v in p["files"].values():
            self.assertRegex(v["sha256"], r"^[a-f0-9]{64}$")

    def test_pin_rejects_changed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            path.write_text('{"format":1}')
            expected = t.sha(path.read_bytes())
            self.assertEqual(t.load_pinned(path, expected), {"format":1})
            path.write_text('{"format":2}')
            with self.assertRaises(ValueError):
                t.load_pinned(path, expected)


class GenuineSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = HERE.parents[3] / "toolchain/iig-generated-diagnostic26b"
        cls.source = Path(os.environ.get("MTK_IIG_DIAGNOSTIC", str(default))) / "DriverKit"
        if not cls.source.is_dir():
            raise unittest.SkipTest("preserved genuine output absent; no synthetic RPC substitute")
        cls.profile = json.loads(t.PROFILE.read_text())["files"]
        cls.original = {}
        for name, metadata in cls.profile.items():
            data = (cls.source / name).read_bytes()
            if t.sha(data) != metadata["sha256"]:
                raise ValueError("genuine artifact differs: " + name)
            if name.endswith(".iig.cpp"):
                cls.original[name] = data.decode()

    def test_all_actual_shapes_and_entry_order(self):
        total = 0
        for name, original in self.original.items():
            text, counts = t.transform_impl(original, self.profile[name])
            total += counts["request_entry_bounds"]
            self.assertNotIn("kernelContent", text)
            self.assertNotIn("messageContent", text)
            self.assertNotIn("IORPCMessageFromMach(", text)
            self.assertIn("static_assert(sizeof(IORPC) == 24", text)
            # Every typed invocation begins with the checked helper before any
            # generated MESSAGE_CONTENT-dependent local initializers.
            entries = re.findall(r"if \(!mtk_iig_legacy_request\(_rpc, sizeof\((\w+)_Msg_With_Content\),"
                r"\n[^\n]+\n[^\n]+\n    \1_Invocation rpc = \{ _rpc \};", text)
            self.assertEqual(len(entries), self.profile[name]["invocations"])
            self.assertEqual(text.count("if (!reply || rpc.replySize < sizeof(*reply))"),
                             self.profile[name]["reply_required"])
        self.assertEqual(total, 94)

    def test_unknown_shape_and_count_rejected(self):
        name = "IOUserClient.iig.cpp"
        original, profile = self.original[name], self.profile[name]
        for changed in (original + "\nvoid unexpected() { rpc.kernelContent = 0; }\n",
                        original.replace("messageContent = rpc.kernelContent;", "messageContent=rpc.kernelContent;", 1),
                        original.replace("const IORPC rpc;", "const IORPC rpc;\n uint64_t unsupported_slot;", 1)):
            # Extra nonmatching fields are caught by the pristine input hash;
            # ABI patterns are additionally rejected by the counted transform.
            self.assertNotEqual(t.sha(changed.encode()), profile["sha256"])
        with self.assertRaises(ValueError):
            t.transform_impl(original + "\nrpc.kernelContent;\n", profile)
        with self.assertRaises(ValueError):
            t.transform_impl(original.replace("messageContent = rpc.kernelContent;", "messageContent=rpc.kernelContent;", 1), profile)
        with self.assertRaises(ValueError):
            t.transform_impl(original, dict(profile, invocations=profile["invocations"] + 1))

    def test_special_reply_paths_are_bounded(self):
        name = "IODispatchSource.iig.cpp"
        text, counts = t.transform_impl(self.original[name], self.profile[name])
        self.assertEqual(counts["work_reply_bounds"], 1)
        self.assertEqual(counts["work_invoke_reply_bounds"], 1)
        self.assertEqual(counts["work_reply_required_object"], 1)
        self.assertEqual(counts["work_invoke_reply_required_object"], 1)
        self.assertIn("message = mtk_iig_legacy_message(rpc, true);\n            if (!message || message->objectRefs < 1)", text)
        self.assertIn("replyMessage = mtk_iig_legacy_message(rpc.rpc, true);\n    if (!replyMessage || replyMessage->objectRefs < 1)", text)
        self.assertLess(text.index("if (!message || message->objectRefs < 1)"), text.index("message->objects[0]"))
        self.assertLess(text.index("rpc.message   = rpc.reply;"), text.index("rpc.reply     = NULL;"))
        name = "IOInterruptDispatchSource.iig.cpp"
        text, counts = t.transform_impl(self.original[name], self.profile[name])
        self.assertEqual(counts["interrupt_reply_write_bounds"], 1)
        self.assertIn("if (!msg || rpc.replySize < sizeof(*msg)) return (kIOReturnIPCError);\n\n    memset(msg", text)

    def test_reply_version_matches_every_ordinary_producer(self):
        producers = checks = 0
        for name, original in self.original.items():
            text, counts = t.transform_impl(original, self.profile[name])
            n = original.count("reply->mach.msgh.msgh_id   = kIORPCVersion190615Reply;")
            self.assertEqual(counts["ordinary_reply_protocol"], n)
            producers += n
            checks += text.count("if (rpl->mach.msgh.msgh_id != kIORPCVersion190615Reply)")
        self.assertEqual(producers, 85)
        self.assertEqual(checks, producers)


class ActualCLINegatives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = HERE.parents[3] / "toolchain"
        cls.generated = Path(os.environ.get("MTK_IIG_DIAGNOSTIC", str(root / "iig-generated-diagnostic26c")))
        cls.inputs = Path(os.environ.get("MTK_IIG_INPUTS", str(root / "iig-inputs-8796-build21-diagnostic26c")))
        if not (cls.generated / "generation.json").is_file() or not (cls.inputs / "inputs.json").is_file():
            raise unittest.SkipTest("successful diagnostic manifests absent")
        report = json.loads((cls.generated / "generation.json").read_text())
        if report.get("status") != "diagnostic-generated-not-compatible":
            raise unittest.SkipTest("actual CLI tests require successful preserved diagnostic run")
        cls.generation_hash = t.sha((cls.generated / "generation.json").read_bytes())
        cls.input_hash = t.sha((cls.inputs / "inputs.json").read_bytes())
        if report.get("inputs_sha256") != cls.input_hash:
            raise ValueError("actual input/diagnostic manifests differ")

    def invoke(self, generated, output, helper):
        return subprocess.run([sys.executable, str(HERE / "legacy_transform.py"),
            "--generated", str(generated), "--generation-sha256", self.generation_hash,
            "--inputs", str(self.inputs), "--input-sha256", self.input_hash,
            "--helper", str(helper), "--output", str(output)],
            capture_output=True, text=True, timeout=30)

    def test_modified_pristine_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); generated = root / "genuine"
            shutil.copytree(self.generated, generated)
            with (generated / "DriverKit/IOMemoryMap.iig.cpp").open("a") as stream:
                stream.write("\n// unauthorized modification\n")
            result = self.invoke(generated, root / "output", HERE / "MTKIIGLegacy.h")
            self.assertEqual(result.returncode, 1)
            self.assertIn("unreviewed/changed generated source", result.stderr)
            self.assertFalse((root / "output").exists())

    def test_changed_manifest_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); generated = root / "genuine"; generated.mkdir()
            (generated / "generation.json").write_bytes((self.generated / "generation.json").read_bytes() + b"\n")
            result = self.invoke(generated, root / "output", HERE / "MTKIIGLegacy.h")
            self.assertEqual(result.returncode, 1)
            self.assertIn("pinned manifest hash mismatch", result.stderr)
            self.assertFalse((root / "output").exists())

    def test_existing_output_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "output"; output.mkdir()
            (output / "sentinel").write_bytes(b"unchanged")
            result = self.invoke(self.generated, output, HERE / "MTKIIGLegacy.h")
            self.assertEqual(result.returncode, 1)
            self.assertIn("output must be new", result.stderr)
            self.assertEqual(list(output.iterdir()), [output / "sentinel"])
            self.assertEqual((output / "sentinel").read_bytes(), b"unchanged")

    def test_helper_symlink_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); helper = root / "helper.h"
            helper.symlink_to(HERE / "MTKIIGLegacy.h")
            result = self.invoke(self.generated, root / "output", helper)
            self.assertEqual(result.returncode, 1)
            self.assertIn("helper must be a regular", result.stderr)
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
