Guarded SSPM observation: tested, not integrated
===============================================

This standalone loader primitive executes a fixed subset of inherited SSPM
reads and contains one precise local synchronous-abort case. It advances the
physical investigation without treating zero SECURITY_AO words as permissions.
It does not start firmware, acknowledge traffic, write MMIO, enter XNU, or grant
SSPM, clock or PMIC ownership. Production loader/linker/builder/reader and
kernel sources remain unchanged. No phone execution has been performed.

The initial implementation and design were imported from old-tree checkpoint
``2d16066b``. The design/evidence files in the parent directory remain historical
design snapshots. This directory's ``validation-evidence.json`` records the
new-tree execution audit. Current ``../start.S``, ``../loader.c`` and
``../loader.ld`` still match their design-snapshot hashes.

Test and reproduce
------------------

From the kernel source root::

  python3 tools/mt6762/physical/sspm/test_probe.py
  python3 tools/mt6762/physical/sspm/audit.py --output /tmp/sspm-audit.json

The fixture compiles the actual ``probe.c``, ``guard.S`` and current production
``start.S`` with the existing Cortex-A53 freestanding compiler flags, including
``-mgeneral-regs-only -mstrict-align -ffixed-x28``. It executes their ordinary
AArch64 instructions in Unicorn. Exception entry, ERET, system registers,
barriers and the counter are explicitly modeled; this is not an emulation of
the interconnect, secure world or physical permission checks. Python packages
``unicorn``, ``capstone`` and ``pyelftools`` are required. ``IOS_CC`` can select
a compatible clang/lld; the default uses the existing project toolchain.

Fifteen test groups cover every one of the 26 possible first-fault positions,
all 13 direct indices with success/abort, every other vector slot, negative
syndrome/PC/FAR/CPU/context predicates, nested faults, invalid buffers, entry
refusal, changing profiles, zero/nonzero/changing values, time reversal,
deadline expiry, frozen time, stalled reads, interrupted fault metadata and
malformed/foreign records. Tests assert disarming before ERET, unchanged failed
output, all GPR and flag restoration, stack alignment, DAIF/VBAR restoration,
exact successful prefixes and no protected stores. A post-load SError or
barrier-PC abort delegates to the existing fatal path and remains incomplete.
An unmapped external screen read is explicitly outside the protected load.

The tests exposed and fixed a real prototype defect: destination validation
excluded only the wrapper's 288-byte frame. A fault destination inside the
future 256-byte exception frame corrupted saved registers. ``guard.S`` now
excludes both frames. Both overlapping output and fault pointers are rejected
before any protected access, and the planted buffer bytes remain unchanged.

Integration contract
---------------------

1. Add an explicit loader-only diagnostic mode after the existing entry/FDT/RAM
   admission and before XNU handoff. It must be incompatible with entering XNU
   or enabling any SSPM/DVFS/clock/PMIC capability. Use only the boot CPU; keep
   secondary CPUs and inherited watchdog policy unchanged. On return, retain
   the record and halt under the existing recovery policy.
2. Reserve a separate 1024-byte, 64-byte-aligned record in the actual linker
   and Image; pass its address to ``sspm_probe_run(record, identity)``. The
   proposed ``0x40085400`` is allocated ONLY in ``fixture.ld``. Production
   ``loader.ld`` currently starts ``.text`` immediately after the peripheral
   record at that address: inserting a new output section must shift/relink
   the text. Assert record size/address, no overlap, DA prefix containment,
   both 2048-byte-aligned vector tables, stack alignment and Image/FDT bounds.
   Review the DA reader's exact reservation and capture identity handling.
3. Supply a 32-byte intended-image identity in owned Image RAM, disjoint from
   the record. Use the same compiler flags as the fixture; reserve x28 as zero
   across all loader C. The runtime requires EL1h, boot CPU affinity zero,
   SCTLR_EL1 M/C/EE clear, DAIF masked, 13 MHz CNTFRQ and VBAR_EL1 equal to the
   existing ``physical_vectors``. A valid, owned, 16-byte-aligned loader stack
   is a caller prerequisite; initial stack faults are not contained. The
   low-level wrapper and handler require 544 bytes in addition to the C
   caller's frame. These are physical addresses in the admitted MMU-off
   regime; no page tables or EL2/EL3 permissions are modified.
4. Link both implementation files, export their final load PC and old VBAR
   into the manifest, and audit the final production layout/disassembly.
   ``sspm_guard_context`` must be in zeroed BSS. The record must be fresh
   output storage, never code, stack, the identity, or another live object.
   Image-range checks are defensive bounds, not a sandbox for hostile callers.
5. Capture exactly 1024 bytes and decode against the intended manifest::

     python3 tools/mt6762/physical/sspm/decode.py record.bin \
       --identity EXPECTED_64_HEX_DIGITS --load-pc FINAL_LOAD_PC \
       --physical-vectors FINAL_ORIGINAL_VBAR

   The decoder checks identity, size/version, inverse pairs, addresses,
   successful-prefix validity, reserved bytes, admitted profile and exact
   committed-abort predicate. It returns observations with both ownership
   booleans false. Inverse pairs are not an authenticated record or checksum;
   interrupted ordinary updates can be rejected as torn evidence.

The low-level ``sspm_guard_read(index, output, fault)`` returns 0, -1 or -2 for
completion, the admitted abort, or refusal. There is no arbitrary-address
argument. Output and the 32-byte fault buffer must be aligned Image RAM,
disjoint from one another, context, wrapper and possible handler frame. Output
is published after the completion barrier, remains untouched on failure, and
the fault buffer remains untouched on success. Normal/recovered return
preserves x1..x30, NZCV, SP, DAIF and VBAR; x0 is the result. ESR/FAR/SPSR and
the recovery ELR remain exception state, not promised caller-preserved values.

Exception and memory audit
---------------------------

The sole recoverable instruction is ``sspm_guard_load: ldr w17,[x16]``.
The temporary table's current-EL/SPx synchronous slot checks exact PC,
EC=0x25, IL=1, DFSC=0x10, WnR/CM/S1PTW/FnV clear, exact FAR/index/address,
MPIDR, EL1h SPSR/DAIF and single-use context. EA is recorded without inventing
a cause. It disarms before ERET to ``sspm_guard_failed``. All other cases
branch to the corresponding original vector slot. On nested faults x28=1
preserves the existing immediate-halt recursion rule. The fixture executes
that old branch and halt predicate. Ordinary unsupported cases stop at the
old-vector boundary; the existing fatal diagnostic may subsequently write
its trace and UART as it did before. The new guard has no MMIO stores.

Both stack frames preserve 16-byte alignment. All tested RAM stores remain
inside the linked Image. Hardware pages are read-only in the fixture, and
each hardware access is checked for a listed aligned 32-bit address. There
are at most 26 protected reads: CSRAM 0x00110c00/004/008/00c and 0x00110ea0,
mailbox0 0x10450000 through 0x10450018 in four-byte steps, then OUT_IRQ
0x10451004, twice. IN_IRQ, ACKs, command writes, permission writes and pointer
following are absent. Exact stock ordinary-read provenance and hashes are in
``../SSPM-GUARDED-PROBE-DESIGN.rst`` and
``../../hardware/cpu-power/evidence/sspm-observer-evidence.json``.

Before each region on each pass, the runner rereads the previously captured
external TOP/INFRA/MAINPLL/SPM profile. The SRAM screening interpretation is
BSP-derived, not a physically proven permission predicate. Five SECURITY_AO
words are raw observations; zero and nonzero views are both retained without
granting access. These 78 external loads are not guarded. The latest screen
overwrites earlier values; ``screen_count`` and ``external_valid`` describe
started screens and the last available prefix, not an atomic history.

The 10 ms counter budget bounds dispatch between operations, not transaction
completion. A last operation can complete after that budget. Frozen time
still cannot expand the fixed read count. A stalled load/barrier, a pending
or delayed SError, EL2/EL3 routing and platform error latches remain outside
containment. Modeled SError delivery tests routing only; DAIF.A remains masked
on hardware and a pending SError need not arrive during the probe. A committed
abort means an access failed, without identifying the blocking component.
Uncommitted handler metadata is incomplete evidence, not a confirmed abort.

What the next capture can establish
-----------------------------------

A physical complete record would establish completion of these exact reads
under the recorded inherited profile. Nonzero recognizable CSRAM contents
can guide a separately reviewed expansion to PVT/index/rail observations.
Zero cannot distinguish genuine zero contents from read-as-zero. Stock AP
initialization writes the guards, so even matching guards do not prove SSPM
firmware liveness, version, memory preservation, traffic ownership or CPU-DVFS
readiness. The next transition is a validated physical subset observation,
followed by those missing firmware/state observations; no result here enables
the existing native full observer or active PLL/voltage control automatically.
