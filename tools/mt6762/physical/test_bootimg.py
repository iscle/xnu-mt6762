#!/usr/bin/env python3
"""Boot-v2 container tests; no fastboot/device operations."""
import gzip
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bootimg", HERE / "bootimg.py")
b = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = b
spec.loader.exec_module(b)
STOCK = Path("/home/iscle/Documents/mini_iphone_dump_2/boot.bin")
BSP = Path("/mnt/0da18f53-c547-40a2-a7c3-b08e84d1aab4/alps/aosp-docker/workspace")


def fixture_table():
    fdt = struct.pack(">10I", 0xd00dfeed, 64, 56, 60, 40, 17, 16, 0, 4, 4) + bytes(24)
    return (struct.pack(">8I", 0xd7b7ab1e, 128, 32, 32, 1, 32, 2048, 0) +
            struct.pack(">8I", 64, 64, 0, 0, 0, 0, 0, 0) + fdt)


def fixture():
    header = bytearray(1660)
    header[:8] = b"ANDROID!"
    struct.pack_into("<10I", header, 8, 1, 0x40080000, 0, 0x51b00000, 0, 0,
                     0x47880000, 2048, 2, 0)
    struct.pack_into("<I", header, 1644, 1660)
    struct.pack_into("<Q", header, 1652, 0x47880000)
    parts = dict(kernel=b"k", ramdisk=b"", second=b"", recovery_dtbo=b"", dtb=fixture_table())
    model = b.BootImage(bytes(header), 2048, parts, {}, 0, b"", "fixture", None)
    return b.parse(b.pack(model, b"k", b"r"))


class FormatTests(unittest.TestCase):
    def test_roundtrip_sizes_recovery_offset_and_id(self):
        image = fixture()
        image.parts["second"] = b"second"
        image.parts["recovery_dtbo"] = b"recovery"
        raw = b.pack(image, b"K" * 2049, b"R" * 4097)
        parsed = b.parse(raw)
        self.assertEqual(parsed.parts["kernel"], b"K" * 2049)
        self.assertEqual(parsed.offsets["ramdisk"], 6144)
        self.assertEqual(struct.unpack_from("<Q", parsed.header, 1636)[0], parsed.offsets["recovery_dtbo"])
        self.assertEqual(b.pack(parsed, parsed.parts["kernel"], parsed.parts["ramdisk"]), raw)

    def test_malformed_bounds_version_and_hash(self):
        original = b.pack(fixture(), b"k", b"r")
        variants = [original[:100], original[:-1]]
        for offset, value in ((40, 3), (36, 3), (8, 0xffffffff), (1644, 1648), (1636, 4096)):
            changed = bytearray(original); struct.pack_into("<I", changed, offset, value); variants.append(changed)
        changed = bytearray(original); changed[2048] ^= 1; variants.append(changed)
        for raw in variants:
            with self.assertRaises(ValueError): b.parse(raw)

    def test_dtb_entry_and_fdt_bounds(self):
        original = fixture_table()
        for offset, value in ((4, 127), (16, 100), (36, 127), (32, 65), (64, 0), (64 + 8, 1000)):
            changed = bytearray(original); struct.pack_into(">I", changed, offset, value)
            with self.assertRaises(ValueError): b.dt_table(changed)

    def test_gzip_is_single_bounded_image(self):
        raw = bytearray(128); raw[56:60] = b"ARM\x64"
        packed = gzip.compress(raw, mtime=0)
        self.assertEqual(b.kernel_gzip_info(packed)["size"], 128)
        for changed in (bytes(raw), packed[:-1], packed + b"extra", packed + packed,
                        gzip.compress(b"not an Image", mtime=0)):
            with self.assertRaises(ValueError): b.kernel_gzip_info(changed)
        with self.assertRaises(ValueError): b.kernel_gzip_info(packed, limit=127)

    def test_commandline_and_address_override(self):
        raw = b.pack(fixture(), b"k", b"r", {"ramdisk":0x53000000}, "x" * 600)
        parsed = b.parse(raw)
        self.assertEqual(parsed.address("ramdisk"), 0x53000000)
        self.assertEqual((parsed.header[64:576] + parsed.header[608:1632]).rstrip(b"\0"), b"x" * 600)
        for text in ("x" * 1536, "embedded\0NUL"):
            with self.assertRaises(ValueError): b.pack(fixture(), b"k", b"r", cmdline=text)
        with self.assertRaises(ValueError): b.pack(fixture(), b"k", b"r", {"kernel":1 << 32})

    def test_actual_cli_creation_and_rejection_guards(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "template").write_bytes(b.pack(fixture(), b"k", b"r"))
            kernel = bytearray(128); kernel[56:60] = b"ARM\x64"
            (root / "kernel").write_bytes(kernel); (root / "ramdisk").write_bytes(b"explicit-data")
            base = [sys.executable, str(HERE / "bootimg.py"), "pack", "--template", str(root / "template"),
                    "--kernel", str(root / "kernel"), "--gzip-kernel", "--ramdisk", str(root / "ramdisk")]
            output = root / "new.img"
            cmdline = ["--cmdline", "bootopt=64S3,32N2,64N2"]
            subprocess.run(base + cmdline + ["--output", str(output)], check=True, capture_output=True)
            parsed = b.parse(output.read_bytes())
            self.assertEqual(parsed.parts["ramdisk"], b"explicit-data")
            report = json.loads(Path(str(output) + ".json").read_text())
            self.assertFalse(report["avb_signature_created"])
            self.assertFalse(report["writes_device"])
            original = output.read_bytes()
            again = subprocess.run(base + cmdline + ["--output", str(output)], capture_output=True)
            self.assertEqual(again.returncode, 1); self.assertEqual(output.read_bytes(), original)
            for index, flags in enumerate((["--cmdline", "missing-bootopt"],
                cmdline + ["--kernel-address", "0x40080004"])):
                target = root / ("rejected%d.img" % index)
                result = subprocess.run(base + flags + ["--output", str(target)], capture_output=True)
                self.assertEqual(result.returncode, 1); self.assertFalse(target.exists())


@unittest.skipUnless(STOCK.is_file(), "actual supplied stock dump unavailable")
class StockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = STOCK.read_bytes(); cls.stock = b.parse(cls.raw)

    def test_exact_stock_roundtrip_without_avb_trailer(self):
        image = self.stock
        output = b.pack(image, image.parts["kernel"], image.parts["ramdisk"])
        self.assertEqual(output, self.raw[:image.payload_end])
        self.assertEqual(image.header[576:596].hex(), "5b1326f1715379ddb574eb332e0b78e52724737c")
        self.assertEqual(image.footer["original_size"], image.payload_end)
        self.assertIsNone(b.parse(output).footer)
        self.assertEqual(b.dt_table(image.parts["dtb"])["entries"][0]["size"], 109716)
        self.assertGreater(b.kernel_gzip_info(image.parts["kernel"])["size"], 64)

    @unittest.skipUnless((BSP / "system/core/mkbootimg/mkbootimg.py").is_file(), "reference mkbootimg unavailable")
    def test_independent_bsp_mkbootimg_matches_stock_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("kernel", "ramdisk", "dtb"):
                (root / name).write_bytes(self.stock.parts[name])
            command = [sys.executable, str(BSP / "system/core/mkbootimg/mkbootimg.py"),
                "--kernel", str(root / "kernel"), "--ramdisk", str(root / "ramdisk"),
                "--dtb", str(root / "dtb"), "--header_version", "2", "--base", "0",
                "--kernel_offset", "0x40080000", "--ramdisk_offset", "0x51b00000",
                "--second_offset", "0", "--tags_offset", "0x47880000", "--dtb_offset", "0x47880000",
                "--pagesize", "2048", "--os_version", "12.0.0", "--os_patch_level", "2024-03-01",
                "--cmdline", "bootopt=64S3,32N2,64N2 buildvariant=user", "-o", str(root / "reference.img")]
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            self.assertEqual((root / "reference.img").read_bytes(), self.raw[:self.stock.payload_end])


if __name__ == "__main__": unittest.main()
