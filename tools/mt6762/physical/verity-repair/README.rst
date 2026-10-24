Warning-state repair preparation
===============================

This tool prepares local review artifacts. It has no flash-write, connection,
unlock, relock, reset or persistent-storage deletion command. It does not make
fastboot's separate image-cache bug work and does not guarantee a warning will
stay cleared if hardware reports a new corruption event.

The exact LK audit in ../lk-runtime-audit.rst identifies seccfg word0x10 as
dm-verity status. mtkclient calls that word critical_lock_state and sets it to1
while unlocking. This planner requires lock3 and retains it. It changes only
word0x10 to0, its authenticated SHA256 field at0x1c..0x3b, and, when present,
the32-byte value of the exact23-byte key avb.managed_verity_mode. It neither
removes descriptors nor recreates the persistent table. Unrelated data,
including sector padding, is preserved byte for byte. Unknown formats fail.

Persistent descriptors are big-endian, packed without inter-record alignment.
The observed record at0x240 has key length23 and value length32; its value is
at0x263..0x282 inclusive. The parser walks at most8 records from the known
64-byte version1.0 header at0x200, rejects duplicates, malformed termination,
unsupported lengths and out-of-bounds descriptors. It locates the key by exact
bytes, not a raw substring scan. An absent record remains absent.

Offline inspection::

  python3 planner.py /path/to/complete-fresh-seccfg.bin

This reports structural metadata, not authentication. Existing captures are
not treated as fresh device state or proof that hardware authentication works.

For a separately reviewed live preparation, a caller may pass the already
configured ``mtk`` object used inside mtkclient Main/DaHandler to::

  from mtk_adapter import prepare_from_connected_mtk
  report = prepare_from_connected_mtk(mtk, new_output_directory, mtk_checkout)

The adapter requires tracked-clean commitfa97df7df41140e60f215f24eea82cb46faf9ff0,
the imported SecCfgV4 module from that checkout, live hardware code0x766,
XFLASH,512-byte sectors and the exact live seccfg GPT extent0xf000000/8MiB.
It reads that partition freshly, saves a private backup, calls the existing
SecCfgV4.parse and requires the observed hardware V4 authentication variant.
It calls the same V4 encryption primitive used by create(), with
encrypt=True,legacy=True, but does not call create('unlock') or modify its
state fields. The new candidate must independently pass SecCfgV4.parse again.
A second complete device read must equal the first before candidate publication.

Live preparation uses SEJ hardware register operations through the existing DA;
it is not hardware-read-only, although it makes no persistent flash writes.
The adapter does not choose or establish a device connection. Parent orchestration
owns any separately authorized connection and subsequent write decision.

Output is a new mode0700 directory containing mode0600 fresh backup, complete
candidate, changed512-byte sectors and report.json. The report includes hashes,
exact allowed ranges, sector addresses and preservation checks. The whole8MiB
candidate is for review; its presence is not an instruction to rewrite8MiB.
There is deliberately no apply flag. Any later application must independently
check the fresh-before hashes, review the exact sectors, and verify complete
readback against the candidate; this helper does not perform that operation.

Tests::

  MTK_CHECKOUT=/path/to/reviewed/mtkclient python3 -m unittest -v test_repair.py

The imported-parser tests use an explicitly synthetic reversible SEJ test double.
They verify API selection, error handling and preservation, not real hardware
cryptography. A separate live parse/generation/reparse and full readback was
completed on 2026-10-24; see applied-evidence.json. It retained unlock state3,
wrote only the first two512-byte sectors and preserved all unrelated bytes.
Whether the warning is absent after restart still requires physical observation.
