Reset-held digital CONN power stage
==================================

``conn_power.c`` is an original, callback-based implementation of the digital
portion of the shipped MT6762 connectivity power sequence. Its only successful
endpoint is RESET_HELD_ID_VERIFIED: ordinary register 0x180b1010 returned
0x10020300 while the MCU reset was last observed asserted. It does not implement
Wi-Fi readiness, firmware loading, reset release, WMT function-on, PDMA or RF.
There is no loader/kernel call site or device access in these files.

The code defaults off through the mandatory ``enabled`` argument. Zero returns
DISABLED without invoking any callback; only exactly one executes. The public
entry point is ``mt6762_conn_power_reset_held(io, report, enabled)``.

Prerequisites belong to the caller
---------------------------------

Before enabling this stage, an independently validated owner must establish
the board-specific PMIC rail sequence and ramp, external-LDO branch, inherited
or deliberately owned oscillator policy, A-die interface pinmux/delay, correct
AP mapping/access and SPM write access, real reserved CONSYS/Wi-Fi RAM, remap
representability and installed EMI permissions. Neither a supplied boolean nor
a zero return from ``prerequisites`` independently proves these facts. The
callback is an explicit integration contract, not a secure permission oracle.

The owner must hold exclusive digital-sequence ownership for the entire call,
coordinate shared rails/clocks/PMIC users, and keep those resources alive until
a separate lifetime/recovery owner takes over. It must provide fresh actual
prerequisite checks through the callback, invoked before every MMIO operation
and again before returning success. This module neither acquires those external
owners nor programs PMIC, oscillator, pinmux, EMI, memory maps or interrupt/DMA
state. Callback failure stops subsequent accesses. A report is not an ADT grant.

The passive ``connectivity_probe.h`` survey may inform the caller's validation;
it cannot by itself confer any of the above ownership. Cold-state checks below
are live digital observations, independent of any decoder-provided list.

Exact sequence and additions
---------------------------

Before any writes, two sequential masked snapshots require:

* SPM 0x1000632c bits 4:0 == 0x12 (isolated, clock disabled, both power requests
  and domain RESET_B clear); 0x10006180 and 0x10006184 bit 1 both clear.
* Ordinary 0x10001220/0x10001228 protection enable/ack masks 0x16000 asserted,
  and 0x10001250/0x10001258 mask 0x40000 asserted.
* RGU 0x10007018 key readback byte either zero or 0x88. Its MCU reset bit 12
  may already be asserted. Other readable key encodings are rejected.

These snapshots are sequential, not atomic, and require caller serialization.
The cold predicate is intentionally strict and is derived from the shipped
power-off register sequence; it has not been observed to match a live phone's
full cold snapshot. An unexpected inherited state is rejected, not normalized
by arbitrary writes.

The nine writes are:

1. RGU 0x10007018: ``old | 0x88001000``, then ordinary bit-12 readback.
2. SPM 0x1000632c: set bit 2 (owned low field 0x12 -> 0x16).
3. Same SPM word: set bit 3 (0x16 -> 0x1e); wait for BOTH status bit-1 values.
4. Same word: clear clock-disable bit 4 (0x1e -> 0x0e).
5. Same word: clear isolation bit 1 (0x0e -> 0x0c).
6. Same word: set domain RESET_B bit 0 (0x0c -> 0x0d). This is separate from
   RGU MCU reset bit 12, which remains asserted.
7. INFRA CLR 0x100012a4: write 0x14000 (bits 14 and 16 only).
8. Same CLR word: write 0x2000 (bit 13 only).
9. INFRA1 CLR 0x100012ac: write 0x40000 (bit 18 only).

All SPM transitions re-read the live old word, require the expected owned
field, preserve all other bits, and verify the new owned field. Reset is checked
before each transition; both power acknowledgments are freshly checked before
the clock/isolation/domain-reset transitions and each protection release.
Barriers bracket every write. Only the two CLR command aliases are written;
neither alias is read.

The write order follows exact shipped code. Bounded ordinary enable/ack
readbacks after each protection release are a deliberate new diagnostic
requirement: the stock release function does not wait for them. The code then
waits at least 10 us and checks the complete ready snapshot (RGU held, SPM 0x0d,
both power acknowledgments on, both protection masks clear) before each ID load.
Only 0x180b1010 is accessed in the powered CONN domain, and it is only read.

The ID is sampled at most ten times, with 20 ms between unsuccessful samples,
within a 200 ms stage deadline. The final failed sample returns immediately;
there is no purposeless final 20 ms sleep. A matching ID returned after a
deadline is retained diagnostically but does not produce success. The rest of
the shipped ``polling_consys_chipid`` function is intentionally excluded: it
loads a ROM patch and performs connectivity configuration writes.

Bounds and failure ownership
----------------------------

The caller supplies a proven 13 MHz counter, 1..100000 us transition timeout,
1..1000000 us total timeout, and a 1..10000000 per-stage iteration limit. The
proposed transition/total limits are engineering bounds, not silicon timing
specifications. Every hardware callback has before/after elapsed-time checks;
polling and minimum-delay loops also have iteration bounds. Iteration exhaustion
may stop a diagnostic before its time budget, depending on CPU and callbacks.
Counter wrap is handled through unsigned elapsed arithmetic. A frozen timer
cannot satisfy the mandatory settle delay or make a polling loop infinite.

Callbacks themselves must be bounded. These software limits cannot interrupt
a stalled MMIO load, hung interconnect, synchronous abort or asynchronous SError.
No exception recovery is installed. ``relax`` must be bounded/nonblocking;
``barrier`` must provide real device ordering when integrated.

Any failure returns immediately, preserving stage, original callback error,
counts, timestamps, latest snapshot words and ID if successfully read. The last
value has explicit validity/access-kind flags: a write value is the requested
value, not measured readback, and failed read output is not committed. Snapshot
fields are last successful observations and may come from different times.

There is no automatic retry or rollback, reset release, power-off, protection
reassertion, clock gate change or shared-rail shutdown. A failed write may have
reached hardware. The caller must keep its ownership and shared resources until
it has diagnosed the retained state. The core never deliberately releases MCU
reset; if an external owner clears it or access fails, a previous reset
observation cannot guarantee its current value. Do not blindly reassert reset
or power off after ownership is lost.

Primary evidence
----------------

``conn_power_evidence.json`` records artifact and source digests. The selected
stock-kernel disassembly bytes were previously verified against the dumped
Image. Stock function references are Image offsets, WMT references are .text
section offsets, not addresses in the new implementation:

* ``wmt_drv.ko`` .text+0x2508..0x251c: RGU +0x18 read, OR 0x88001000,
  write and DSB. The supplied MT6765 header lines 126..127 independently names
  bit 12 and key 0x88 << 24.
* Image+0x464ba4..0x464c68: power-request bits 2/3, dual acknowledgments,
  clock-disable clear, isolation clear, domain RESET_B set, with barriers.
  Image+0x464c8c..0x464d44 contains the corresponding power-off path from which
  the strict cold owned-field predicate is derived.
* Image+0x464a38..0x464a70: exact CLR order 0x14000, 0x2000, 0x40000.
  This includes bit 16 missing from the inactive WMT fallback path. Shipped
  WMT .text+0x263c calls the CCF clock framework; inactive fallback loop bugs
  are not part of the shipped sequence used here.
* WMT .text+0x275c..0x2794: expected 0x10020300 and ordinary +0x10 ID load.
  The stock DT maps that bank at 0x180b1000. .text+0x27d4..0x27e4 provides
  the 20 ms interval and ten-attempt counter; .text+0x27c4 already enters ROM
  patch loading on the full stock success path, which this module omits.

Validation
----------

``sh test_conn_power.sh`` executes this C implementation against a stateful
device model. The model verifies the exact nine-write ordering and unrelated
bits, delays the two power acknowledgments independently, delays each protection
ack, refuses powered-ID reads before readiness, and rejects accesses outside
the fixed digital register set. Tests inject errors at every MMIO and fresh
prerequisite callback, including a write which reaches hardware but reports
failure. Cold-state mismatches, ignored reset writes, changed ready state,
all three stuck protection stages, one-sided power status, frozen/wrapping
counters, per-stage/global/late-success deadlines, delayed/wrong ID and 64
unrelated-field patterns are exercised. Finally the actual core is compiled
freestanding for AArch64 with strict warnings and no undefined runtime symbols.
These tests establish software behavior, not physical power-on success.
