Reset-held CONSYS EMI firmware staging
=====================================

This original freestanding core stages the three exact shipped RAM images into
an already owned CONSYS reservation and verifies every transferred byte. It is
default off and has no loader/kernel integration. It does not map or reserve
memory, access MMIO, configure a clock/PMIC/MPU, release MCU reset, issue PDA/WMT
commands, start DMA or enable a radio. No physical staging has been tested.

Exact input profile
-------------------

``cr_stage(request, io, workspace, report)`` accepts an immutable array in this
order. ``cr_profile_at`` exposes the fixed metadata and SHA-256 digests; callers
cannot supply replacement hashes, targets, types or header lengths.

============================ ==== ========== ========== ========== ===========
Filename (prefix soc1_0_)     Type File bytes Body bytes EMI offset Debug offset
============================ ==== ========== ========== ========== ===========
ram_bt_1_1_hdr.bin            0    571085     571037     0x080000   0x68300
ram_wifi_1_1_hdr.bin          3    196208     196160     0x140000   0x68310
ram_mcu_1_1_hdr.bin           4    105940     105892     0x000000   0x68320
============================ ==== ========== ========== ========== ===========

All three images share one 4 MiB CONSYS reservation. The separate WLAN DMA pool
and ``WIFI_RAM_CODE_soc1_0_1_1.bin`` are not used. The original 48-byte headers
are removed. The launcher clears address byte0 (raw0x11); the normalized low24
bits give the table's offsets. Raw type is stored big endian. The date is not
required to contain16 digits: the actual BT image terminates its date with NULs.
This is why the current general ``conn_decode`` parser cannot handle all three
images; it remains unmodified. Exact header fields plus full-file SHA-256 are
checked here, without importing firmware data or using a permissive parser.

All three full-file digests are checked before the first destination write.
Each body is then copied in at most1024-byte chunks, published to the peripheral
view, prepared for uncached/fresh readback and compared bytewise. The exact short
tail is retained. The core also hashes the bytes actually staged and compares
the pinned body digest. After each verified body it stages16 debug bytes: the
first15 original date bytes followed by NUL. Success therefore verifies873137
bytes through857 transfers. Gaps and all other reservation bytes are untouched.

The hash pins bind the artifacts used in this project, not Apple/MediaTek
authentication or physical compatibility. Header CRC fields remain opaque;
SHA-256 here does not claim to implement their algorithm. The source hash
boundary depends on a real immutable-source lease. A violated lease can permit
partial wrong data before the final staged-body hash detects it; the core then
fails with reset still under the caller's control. This is not an atomic copy.

Caller admission and actual observations
---------------------------------------

Before calling, the integration must:

* Commit the current boot's CONSYS range in the common allocation ledger,
  exclude it from every live loader/kernel/DMA allocation, and hold exclusive
  ownership until a later lifetime/recovery owner takes over. A successful
  ``cm_plan`` proposal or a saved capture is insufficient. Stock allocations
  require16 MiB alignment,4 MiB size, and the live FDT allocation intervals;
  the core checks the alignment/size and below4GiB bounds, while the caller
  must enforce the actual FDT/ledger interval and exclusions.
* Preserve the immutable, fully mapped source buffers and the physical-address
  correspondence supplied in each ``cr_source``. The core rejects overlap of
  these source ranges with each other or CONSYS and detects virtual aliases
  with request, IO, workspace and report. All other source/executable/stack/
  framebuffer/allocator exclusions belong to the committed ledger.
* Establish reset-held power/IP admission, stable PMIC/oscillator/clocks,
  bus-master quiescence, external-LDO policy and the exact AP/CONN EMI remap.
  Establish AP write/read and CONN access permissions, including ownership of
  the stock Wi-Fi staging path's MPU protection transition. This core never
  performs or implicitly authorizes that transition.
* Establish nonconflicting mapping/shareability/cache attributes and cache-line
  ownership. The publish callback must make writes visible to CONN with the
  required ordering. Prepare-read must prevent a stale cached alias from making
  readback falsely pass; it cannot merely reread the just-written CPU cache.

``observe`` is called before each source hash/copy step and before every
destination write, cache operation and read. A successful exact run makes5141
observations; this is deliberately conservative and must fit the real deadline.
The callback must perform actual fresh checks under the owner lock and return
current ordinary-read data. The core independently validates these values:

================= ============ =============================================
Observation       Ordinary PA  Predicate
================= ============ =============================================
RGU reset         0x10007018   bit12 set
SPM CONN control  0x1000632c   low5 bits =0x0d
Power ACK pair    0x10006180/4 bit1 set in both
CONN IP           0x180b1010   0x10020300
CONN HW/FW        0x18002000/4 stable full values; FW low8=0
CONSYS remap      0x10001380   low12 = committed base >>24
================= ============ =============================================

The powered0x180 accesses require the earlier digital/power admission. The
hardware version is retained and required stable; it is not compared to header
0x8a00 because the shipped selection does not make that comparison. Firmware
low8=0 reproduces the exact launcher's compatibility predicate for these files.
``observe`` must also revalidate the real protection/rail/clock/access/source
lease invariants that are not represented by these fields. It reports the
owned base, size and nonzero epoch, which must remain equal to the request.
Those software values detect a changed owner; they are not independent proof
of reservation, security permission, source immutability or freshness. Returning
constant snapshots or success booleans cannot satisfy the integration contract.

Callbacks, limits and errors
---------------------------

The IO adapter must implement synchronous bounded ``write``, ``synchronize`` and
``read`` callbacks over exactly the passed physical range. They have no right
to program unrelated hardware. Each data callback returns an explicit completed
length; a short or oversized result is terminal. ``synchronize`` distinguishes
publish from prepare-read. The stateful host consumer enforces that sequence
using separate CPU-cache and DRAM arrays; it is a real callback consumer of the
core, not a mock replacement of the transfer algorithm.

``enabled=0`` returns DISABLED without any callback. Enabled must equal1, the
timer must be the established13 MHz counter, timeout1..5000000 microseconds,
and operation limit1..20000. The unsigned elapsed-time check handles one counter
wrap; backward/unreasonably large movement fails. Time is checked before and
after callbacks. The operation cap and fixed-size loops remain finite with a
frozen timer. A stalled bus or a callback that never returns is not contained by
this C core; adapters must establish their own access and execution bounds.

Inputs and IO descriptors are snapshotted into the caller-owned workspace. On
invalid argument/layout, the output is untouched so a rejected alias cannot
corrupt an input. Otherwise the report is initialized and tracks the failure
phase, raw observations, callback result, attempted/completed counts and last
range/length. A failed write may have reached memory even if it reports zero
completion. The core stops without further IO (a final timer read is allowed),
does no retry/rollback/automatic poweroff, and never changes reset. Caller must
retain reset and ownership on both success and failure. Loss of access/ownership
means the last snapshot cannot establish the current physical reset state.

The workspace/report are ordinary C diagnostics, not an on-device wire ABI.
Do not place the workspace on a small kernel stack. No new kernel header or IIG
generation is needed until an integration deliberately includes this core.

Source evidence and validation
-----------------------------

``evidence.json`` pins the primary shipped artifacts and exact relevant code
ranges from the private ``wifi-native/rompatch`` audit. The shipped module
``mtk_wcn_soc_rom_patch_dwn`` at .text+0x25d0c supplies the type loop,48-byte
header skip, low24-bit destination, memcpy_toio and debug-time copy. Launcher
VA0x62b8/0x6358..0x638c supplies the normalized address/type. Exact helper
instructions were exercised in Unicorn during that audit. No binary/source
equivalence is assumed for the BSP's misleading32-byte comment or its inactive
branches. Stock silently succeeds on some mapping errors; this core reports
those errors and verifies readback instead.

Portable primitive tests and strict freestanding AArch64 compile::

  bash test.sh

Full stateful tests with locally held originals, in fixed order::

  bash test.sh /private/soc1_0_ram_bt_1_1_hdr.bin \
      /private/soc1_0_ram_wifi_1_1_hdr.bin /private/soc1_0_ram_mcu_1_1_hdr.bin

Repeat the latter with ``SANITIZE=1`` for AddressSanitizer/UndefinedBehaviorSanitizer.
Without private files the test explicitly skips exact-image staging; it does
not substitute synthetic trusted digests. Tests cover all-image prevalidation,
source/header tampering, stage order/exact tails/timestamps, untouched gaps,
short/error writes and reads, cache faults, changed live state/owner, source
mutation after validation, timer wrap/backwards/freeze, deadlines, bounds and
overlap. There is no phone access or firmware distribution in these tests.
