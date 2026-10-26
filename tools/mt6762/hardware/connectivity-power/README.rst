Passive connectivity survey, record version 1
============================================

``../../physical/connectivity_probe.h`` collects two sequential observations
of 21 AP and 19 PMIC ordinary words. This is a prerequisite observation for
native connectivity power work; it does not power CONN, grant ownership, or
show that firmware or an oscillator is running. The closed address list and
source references are in ``registers.json``. No address in the CONN 0x180xxxxx
domain, SET/CLR alias, ADC request, IRQ acknowledgment or oscillator AUXOUT
selector is included.

Integration contract
--------------------

The owner calls ``mt6762_connectivity_capture(io, record, identity, enabled)``
only after reserving a writable, aligned 4096-byte record. Exactly ``enabled=1``
executes hardware callbacks. Zero initializes a DISABLED record without calling
any callback, including the barrier/timer. All other values fail. No default
hardware call site or compile-time enable is supplied by this module. A loader
integration must default its flag off and must not turn survey completion into
an ADT ownership grant.

The proposed retained range is [0x40085400, 0x40086400), immediately following
the peripheral record. The module does not allocate or reserve this range.
The linker, producer, reader and XNU memory exclusions must agree before use.
The owner must retain/cache-clean the completed or failed record. State commits
alone do not flush cache or independently establish physical retention.

Provide bounded callbacks with zero indicating success, output untouched on
failure, and an ordering barrier. The timer must be the proven 13 MHz counter.
The default global budget is 250000 us, configurable from 1 through 1000000 us.
The collector makes at most 80 read calls, without retries, and stops at the
first transport error, clock rejection, PMIC family mismatch or elapsed budget.
Times are unsigned 64-bit counter values; modular elapsed arithmetic tolerates
wrap. Even a frozen timer cannot cause an infinite collector loop. Budget checks
between calls cannot interrupt a stalled bus or a stuck callback. Synchronous
abort, asynchronous SError and a peripheral hanging the interconnect are not
contained by this code.

``read_ap32`` must enforce the actual loader's mapped, AP-readable whitelist and
live clock admission. The collector checks its earlier same-pass INFRA+0x90
bit 1 before the PWRAP configuration window, but this snapshot does not replace
the callback's live PWRAP gate check. It never follows mutable record addresses.
No supply/reset/protection/pinmux/DMA write callback exists.

``pwrap_readonly.h`` adapts the unchanged native
``bsd/dev/mt6762_power_protocol.h`` LK22 WACS engine. Supply an exclusive bounded
acquire/release pair, the actual register/delay callbacks, and live inherited
LK22 wrapper admission under that ownership. The adapter's admission means
wrapper admission, not an assumed PMIC identity. Every PMIC pass starts with
ordinary HWCID 0x0008; the core requires bits 15:8 == 0x57 before any other PMIC
word. A successful mismatched ID is retained as a valid raw sample, with record
result -6 and no later PMIC access. The low revision byte is not constrained.

WACS necessarily writes a READ command to WACS2_CMD and VLDCLR for that completed
read. These are transport operations, not writes to PMIC registers. The adapter
never sets command bit 31, never retries/reinitializes the wrapper, and latches
any transaction/admission failure. Subsequent calls cannot clear another
owner's pending response. Existing bounded WACS polling and errors are retained.
The owner must not run competing PWRAP users or release ownership while a
transaction is pending. Observation does not authorize later regulator writes.

Frozen wire format
------------------

All fields are little-endian, with no implicit packed/pointer-dependent fields.

* Header: 112 bytes, magic ``MTKCONN1``, version 1, size 4096, 32-byte payload
  identity; state and complement, one-based pass (zero before start), last
  attempted index (0xffffffff before start), two begin and two end counter
  values, frequency/budget, result and original transport error.
* Forty entries at offset 112, each 24 bytes: address u32, bus u8, width u8,
  validity u16, two raw u32 values, two signed i32 errors. Bits 0/1 commit the
  respective pass. Unattempted errors are INT32_MIN. AP indices are 0..20;
  PMIC HWCID is index 21. A successful but late callback retains its valid value
  while the overall record fails the deadline.
* Offset 1072 through 4095: 3024 reserved zero bytes.

States are NOT_STARTED=0, DISABLED=1, READING=2, COMPLETE=3, FAILED=4. Results are
OK=0, OFF=1, ARGUMENT=-1, TRANSPORT=-2, DEADLINE=-3, TIMER=-4, PWRAP_GATED=-5,
PMIC_FAMILY=-6. Per-entry errors describe callbacks or a pre-read rejection;
the separate overall result describes post-read deadline/family rejection.

``record.py initialize --identity HEX64 --output FILE`` emits a pristine
NOT_STARTED packet. ``record.py decode FILE --expected-identity HEX64`` validates
identity, ABI, fixed addresses/widths, state complement, validity, completion,
reserved bytes and family rejection. COMPLETE timestamps must follow first
start, first end, second start, second end, within the global budget; ordering
uses unsigned offsets from first start to permit counter wrap. Equal times
remain valid. NOT_STARTED/DISABLED require all raw sample slots to be zero.
Treat a torn state commit as invalid and
keep the raw file for investigation. Decoding is an offline operation; metadata
must never be used as an MMIO execution list or an ownership grant.

Evidence and interpretation
---------------------------

``provenance.json`` binds the private shipped-artifact audits by digest without
redistributing their binaries. The shipped WMT driver uses CCF for CONN power;
inactive BSP fallback loops do not establish the shipped power sequence. The
stock CCF power/ack/protection functions and WMT reset, pinmux and remap reads
justify the AP words. Two extra pin-control words, 0x10002c00/0x10002c10, are in
the shipped binary but their electrical labels remain unresolved.

The exact stock clkbuf descriptor table proves PWRAP 0x188 bit 1 selects CONN
automation and 0x18c..0x198 contain its four address/data words. PMIC 0x0788,
0x07b0 and 0x044a are mapped by stock DT; optional 0x07ac bit 12 is interpreted
only from the supplied MT6357 BSP header and optional I1 branch. Neither BSP
automation template is asserted to be the actual inherited phone template.
PMIC enable, DA and selector values are digital state, not measured voltage or
frequency. DA stable bit 14 is a BSP interpretation; the shipped regulator
table independently supports DA enable bit 15.

Retained capture40 showed SPM primary/secondary 0x434c, with CONN bit 1 clear,
and INFRA+0x90/+0x94 zero in both observations. This describes that handoff only;
it does not establish current state, all rails off, BTIF configured, or valid
oscillator output. No physical execution of this new collector is claimed by
its host tests.

Validation
----------

Run ``sh test.sh``. It executes the real C collector and existing WACS protocol,
not a duplicate Python model: default-off/no callbacks; malformed inputs;
80 transport fault positions; first/second pass family rejection; gate changes;
deadline before/after reads, counter wrap/freeze; fixed execution addresses even
when retained addresses are altered; all 19 allowed PMIC read commands and
forbidden aliases; all three bounded WACS timeout phases and fault latching.
Python consumes actual complete, partial-failure, wrong-family, counter-wrap
and disabled C packets. It rejects corrupted fields, all inactive nonzero
sample slots, and backwards/overlapping pass timestamps on ordinary or wrapped
counters. Finally a real AArch64 freestanding consumer is
compiled with -Wall -Wextra -Werror and checked for missing runtime symbols.
Set ``CLANG`` to choose the compiler; otherwise the existing project toolchain
is used when clang is absent from PATH. This is not a loader or kernel build.
