#!/usr/bin/env python3
"""Inspect/repack Android boot-v2 files. Never contacts or changes a device.

Preserves template metadata and DTB table, accepts explicit kernel and ramdisk,
recomputes Android's SHA1 image ID, and deliberately omits old AVB/signatures.
"""
import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

HEADER_SIZE = 1660
PARTS = ("kernel", "ramdisk", "second", "recovery_dtbo", "dtb")
SIZE_OFFSETS = dict(kernel=8, ramdisk=16, second=24, recovery_dtbo=1632, dtb=1648)
ADDRESS_OFFSETS = dict(kernel=12, ramdisk=20, second=28, tags=32, dtb=1652)
MAX_DOWNLOAD = 0x08000000  # Exact dumped LK fastboot_init immediate.
MAX_DECOMPRESS = 0x07800000  # Selected BSP platform limit; static LK allocation corroborates it.


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def align(value, page):
    return (value + page - 1) & -page


def image_id(parts):
    result = hashlib.sha1()
    for name in PARTS:
        result.update(parts[name])
        result.update(struct.pack("<I", len(parts[name])))
    return result.digest() + bytes(12)


def dt_table(data):
    if len(data) < 32:
        raise ValueError("truncated Android DT table")
    magic, total, header, entry_size, count, offset, page, version = struct.unpack_from(">8I", data)
    if (magic != 0xd7b7ab1e or total != len(data) or header != 32 or entry_size != 32 or
            offset < header or not count or count > (len(data) - offset) // entry_size or version != 0):
        raise ValueError("unsupported/malformed Android DT table")
    entries, ranges = [], []
    for index in range(count):
        size, start, ident, revision, *custom = struct.unpack_from(">8I", data, offset + index * entry_size)
        if start < offset + count * entry_size or size < 40 or start > len(data) - size:
            raise ValueError("DT table entry outside payload")
        if any(start < end and begin < start + size for begin, end in ranges):
            raise ValueError("overlapping DT table entries")
        ranges.append((start, start + size))
        fdt = data[start:start + size]
        if struct.unpack_from(">2I", fdt) != (0xd00dfeed, size):
            raise ValueError("DT entry is not a complete FDT")
        _, _, structure, strings, reserve, fmt, compatible, cpu, strings_size, structure_size = struct.unpack_from(">10I", fdt)
        if (fmt != 17 or compatible > fmt or reserve < 40 or reserve >= size or
                structure < 40 or structure > size - structure_size or
                strings < 40 or strings > size - strings_size):
            raise ValueError("FDT section bounds/version invalid")
        entries.append(dict(offset=start, size=size, id=ident, revision=revision, custom=custom,
                            sha256=sha256(fdt)))
    return dict(total_size=total, page_size=page, entries=entries)


@dataclass
class BootImage:
    header: bytes
    page_size: int
    parts: dict
    offsets: dict
    payload_end: int
    trailer: bytes
    source_sha256: str
    footer: dict | None

    def address(self, name):
        return struct.unpack_from("<Q" if name == "dtb" else "<I", self.header, ADDRESS_OFFSETS[name])[0]


def parse(data):
    if len(data) < HEADER_SIZE or data[:8] != b"ANDROID!":
        raise ValueError("not a complete Android boot image")
    page, version = struct.unpack_from("<2I", data, 36)
    if version != 2 or struct.unpack_from("<I", data, 1644)[0] != HEADER_SIZE:
        raise ValueError("only exact boot header v2/1660 is supported")
    if page not in (2048, 4096, 8192, 16384):
        raise ValueError("unsupported boot page size")
    parts, offsets, position = {}, {}, page
    for name in PARTS:
        size = struct.unpack_from("<I", data, SIZE_OFFSETS[name])[0]
        if position > len(data) - size or align(position + size, page) > len(data):
            raise ValueError("truncated component/padding: " + name)
        offsets[name] = position
        parts[name] = data[position:position + size]
        position = align(position + size, page)
    if not parts["kernel"] or not parts["dtb"]:
        raise ValueError("kernel and DTB table required")
    recovery_offset = struct.unpack_from("<Q", data, 1636)[0]
    if recovery_offset != (offsets["recovery_dtbo"] if parts["recovery_dtbo"] else 0):
        raise ValueError("recovery_dtbo offset does not match layout")
    if data[576:608] != image_id(parts):
        raise ValueError("Android SHA1 image ID mismatch")
    dt_table(parts["dtb"])
    footer = None
    if len(data) >= 64 and data[-64:-60] == b"AVBf":
        magic, major, minor, original, vbmeta_offset, vbmeta_size = struct.unpack_from(">4sIIQQQ", data, len(data) - 64)
        if (major != 1 or original < position or vbmeta_offset < original or
                vbmeta_offset > len(data) - 64 - vbmeta_size):
            raise ValueError("malformed AVB footer bounds")
        footer = dict(major=major, minor=minor, original_size=original,
                      vbmeta_offset=vbmeta_offset, vbmeta_size=vbmeta_size)
    return BootImage(data[:HEADER_SIZE], page, parts, offsets, position, data[position:], sha256(data), footer)


def pack(template, kernel, ramdisk, addresses=None, cmdline=None):
    if not kernel:
        raise ValueError("kernel must not be empty")
    parts = dict(template.parts, kernel=kernel, ramdisk=ramdisk)
    if any(len(value) > 0xffffffff for value in parts.values()):
        raise ValueError("component too large for boot-v2")
    header = bytearray(template.header)
    for name in PARTS:
        struct.pack_into("<I", header, SIZE_OFFSETS[name], len(parts[name]))
    for name, value in (addresses or {}).items():
        if name not in ADDRESS_OFFSETS or not 0 <= value < 1 << (64 if name == "dtb" else 32):
            raise ValueError("invalid address override")
        struct.pack_into("<Q" if name == "dtb" else "<I", header, ADDRESS_OFFSETS[name], value)
    if cmdline is not None:
        encoded = cmdline.encode("ascii")
        if b"\0" in encoded or len(encoded) > 1535:
            raise ValueError("command line must be ASCII, NUL-free and at most1535 bytes")
        padded = encoded.ljust(1536, b"\0")
        header[64:576], header[608:1632] = padded[:512], padded[512:]
    recovery_offset = template.page_size + sum(align(len(parts[n]), template.page_size) for n in PARTS[:3])
    struct.pack_into("<Q", header, 1636, recovery_offset if parts["recovery_dtbo"] else 0)
    header[576:608] = image_id(parts)
    output = bytes(header).ljust(template.page_size, b"\0")
    for name in PARTS:
        output += parts[name] + bytes(align(len(parts[name]), template.page_size) - len(parts[name]))
    parse(output)  # Independent layout/ID validation before returning bytes.
    return output


def kernel_gzip_info(data, limit=MAX_DECOMPRESS):
    if not data.startswith(b"\x1f\x8b"):
        raise ValueError("MTK bootopt64 path requires a gzip kernel")
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = inflater.decompress(data, limit + 1)
    if len(raw) > limit or inflater.unconsumed_tail:
        raise ValueError("kernel exceeds selected LK decompression capacity")
    if not inflater.eof or inflater.unused_data:
        raise ValueError("kernel must be one complete gzip stream without appended bytes")
    if len(raw) < 64 or raw[56:60] != b"ARM\x64":
        raise ValueError("decompressed kernel lacks the AArch64 Image header")
    return dict(size=len(raw), sha256=sha256(raw), text_offset=struct.unpack_from("<Q", raw, 8)[0],
                image_size=struct.unpack_from("<Q", raw, 16)[0])


def describe(image):
    return dict(format="android-boot-v2", source_sha256=image.source_sha256, page_size=image.page_size,
        header_size=HEADER_SIZE, payload_size=image.payload_end,
        addresses={n:hex(image.address(n)) for n in ADDRESS_OFFSETS},
        cmdline=(image.header[64:576] + image.header[608:1632]).split(b"\0", 1)[0].decode("ascii"),
        image_id=image.header[576:596].hex(),
        components={n:dict(offset=image.offsets[n], size=len(image.parts[n]), sha256=sha256(image.parts[n])) for n in PARTS},
        dt_table=dt_table(image.parts["dtb"]), trailer_size=len(image.trailer), avb_footer=image.footer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    info = commands.add_parser("inspect")
    info.add_argument("image", type=Path)
    create = commands.add_parser("pack")
    for name in ("template", "kernel", "ramdisk", "output"):
        create.add_argument("--" + name, type=Path, required=True)
    create.add_argument("--gzip-kernel", action="store_true", help="compress supplied raw AArch64 Image deterministically")
    create.add_argument("--cmdline")
    for name in ("kernel", "ramdisk", "tags", "dtb"):
        create.add_argument("--" + name + "-address", type=lambda s:int(s, 0))
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            print(json.dumps(describe(parse(args.image.read_bytes())), indent=2))
            return
        if args.output.exists() or args.output.is_symlink() or Path(str(args.output) + ".json").exists():
            raise ValueError("output image and adjacent manifest must be new")
        if args.kernel.stat().st_size > MAX_DOWNLOAD or args.ramdisk.stat().st_size > MAX_DOWNLOAD:
            raise ValueError("individual input exceeds exact dumped LK download capacity")
        template = parse(args.template.read_bytes())
        kernel, ramdisk = args.kernel.read_bytes(), args.ramdisk.read_bytes()
        if args.gzip_kernel:
            kernel = gzip.compress(kernel, compresslevel=9, mtime=0)
        kernel_info = kernel_gzip_info(kernel)
        addresses = {n:getattr(args, n + "_address") for n in ("kernel", "ramdisk", "tags", "dtb")
                     if getattr(args, n + "_address") is not None}
        output = pack(template, kernel, ramdisk, addresses, args.cmdline)
        if len(output) > MAX_DOWNLOAD:
            raise ValueError("image exceeds exact dumped LK128MiB download limit")
        packed = parse(output)
        first_cmdline = packed.header[64:576].split(b"\0", 1)[0].decode("ascii")
        if not re.search(r"(?:^|\s)bootopt=64S3,32N2,64N2(?:\s|$)", first_cmdline):
            raise ValueError("MTK64 packaging requires stock bootopt in the first cmdline field")
        if packed.address("kernel") & 0x7ffff:
            raise ValueError("LK requires a 512KiB-aligned 64-bit kernel load address")
        result = describe(packed)
        result.update(status="unsigned-temporary-boot-container-not-hardware-validated",
            template_sha256=template.source_sha256, kernel_gzip=kernel_info,
            discarded_template_trailer=dict(size=len(template.trailer), avb_footer=template.footer),
            producer_sha256=sha256(Path(__file__).read_bytes()), stock_dtb_preserved=True,
            writes_device=False, avb_signature_created=False)
        with args.output.open("xb") as stream:
            stream.write(output)
        with Path(str(args.output) + ".json").open("x") as stream:
            json.dump(result, stream, indent=2); stream.write("\n")
        print(json.dumps(dict(image=str(args.output), sha256=sha256(output), size=len(output), status=result["status"])))
    except (ValueError, OSError, UnicodeError, zlib.error) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
