Loader RAM trace
================

The diagnostic Image contains a 256-byte record at file offset0x4000,
physical address0x40084000 for the existing Image load base0x40080000.
The linker asserts its address, length and placement below0x40200000.
It is part of the source Image allocation excluded from XNU relocation.
No unowned SRAM, storage, PMIC or clock register is used for this trace.

The0x40200000 bound is NOT the selected DA2 load address: it is the configured
replacement-preloader payload address. Inspection of MTK_DA_V5.bin's selected
zero-based entry22 (DA code0x6765) gives DA2 address0x40000000 and declared
length0x5118c, including a0x100-byte signature. Its declared file range is
therefore [0x40000000,0x4005118c). DA1 is at0x00200000 with length0x39f98.
The trace is outside that DA2 file range. Subsequent exact startup/allocator
analysis establishes BSS [0x40051090,0x4005e2a0) and the stock allocator range
[0x4005e2a0,0x68000000): the trace IS inside that heap. Execution of the original
allocator instructions in the bounded offline model confirms that a normal
1MiB allocation contains the trace. This is a concrete allocator collision,
not proof that every physical connection overwrites the page in the same way.

The opt-in volatile exclusion in da-trace-reservation/README.rst changes only
two audited DA2 heap-base literals to0x40090000, leaving the startup BSS end,
load address and heap end unchanged. Its pinned source, preimage checks,
existing-patcher integration and original-instruction allocation tests are in
that package. It must run before the existing DA1 hash-fix step and upload,
not against an already running DA. A caller must reject the existing unpatched
fallback and verify the selected upload/runtime literals before relying on
this particular exclusion. No phone connection or upload is performed by the
package itself.

This excludes the demonstrated allocator collision only. Preloader DRAM
initialization, DA1/BROM use, reset/power retention, non-heap DMA and fixed
buffers may still overwrite the trace. Reading it immediately on the separately
verified reserved-heap DA connection minimizes additional operations but does
not prove retention. Valid same-build execution markers can provide positive
evidence; absence remains inconclusive. The producer's existing address
assertion does not itself establish a DA reservation. Image5 and recovery2 were
not rebuilt for these documentation corrections, and their frozen manifests
and artifact hashes remain unchanged. Corrected scope and package references
are recorded in trace-build5-evidence.json.

Each build has a fresh256-bit identity derived from random input, the frozen
kernel and source hashes. The exact identity is stored in both the record and
physical-manifest.json. The initialized file has phase0 and sequence0. Only
execution changes those fields. The decoder requires the expected build's
identity, exact magic/version/length, recognized phase, matching phase/sequence
inverse pairs and zero reserved bytes. It rejects truncated, different-build
and malformed records. These checks are not a cryptographic proof of execution
against a hostile writer; the record is a diagnostic, not an attestation.

No record is written until entry EL1/EL2, MMU-off, data-cache-off and little-endian
admission. Therefore an initialized record does not distinguish no entry from
an earlier admission rejection. An absent/malformed record also does not prove
no execution: decompression failure, retention loss or later overwrites remain
possible. Physical RAM retention across resets, preloader initialization and
subsequent DA loading is unproved. Reading this page through a later DA must not
be represented as a guaranteed preserved channel.

Phases
------

======== ====================================
Value   Meaning
======== ====================================
0       Initialized file only
1       Safe RAM-write entry admission
2       EL1 and private stack/BSS ready
3       Entered loader C code
4       Cortex-A53 and13MHz timer accepted
5       Runtime FDT and board accepted
6       Optional inherited console checked
7        512MiB relocation window selected
8       XNU segments copied/zeroed
9       Boot arguments and diagnostic ready
10      Immediately preparing branch to XNU
254     Refused, with reason in detail
255     Fatal exception, register snapshot
======== ====================================

Refusal details1..7 are CPU/timer identity, DTB placement, board compatible,
boot-CPU MPIDR, DTB alignment, GIC SRE, and malformed returned entry respectively.
FDT errors encode0x100 plus the positive parser error number; window errors use
0x200 plus that number. Thus no-window is0x208. Exception fields include ESR,
FAR, ELR, SPSR and the exception EL; the existing recursion guard prevents a
second failed UART report from replacing the first saved exception.

The record also carries original EL, FDT pointer, entry SCTLR/MPIDR, MIDR,
counter frequency, chosen RAM base, boot-argument address and XNU entry address.
previous_phase records the prior completed phase. Metadata can be prepared
before the phase commit, so readers should use the committed phase as the lower
bound on progress, not assume every metadata field changed simultaneously.
Phase10 is NOT proof that XNU executed. Separate kernel/PID1 output established
XNU execution in the synthetic tests below.

Each commit invalidates the old phase inverse, updates sequence and fields,
commits the new inverse, then cleans the bounded record to PoC using CTR_EL0's
minimum data-cache line size and DC CVAC followed by DSB SY. The final assembly
commit preserves the argument and branch-target registers before BR. It adds
no native handoff authorization and leaves watchdog policy unchanged.

Decoding a separately acquired exact256-byte capture
--------------------------------------------------

No phone access is implemented by the decoder::

  python3 tools/mt6762/physical/trace_record.py trace.bin \
    --manifest /path/to/physical-xnu-build5/physical-manifest.json

Use the manifest of the candidate actually selected for the trial. A build4
or another build's data is not a substitute. Recovery-build2 embeds exactly the
same Image/trace identity as physical-xnu-build5; its manifest links the full
diagnostic input hash.

Validation and limits
---------------------

All47 tests discovered by the following command passed::

  python3 -m unittest discover -v -s tools/mt6762/physical -p 'test_*.py'

The narrower five-module command initially reported38 tests; that was not the
full discovery suite. The new five decoder tests cover initialized versus
executed state, identity mismatch, malformed/torn/truncated data, failure details
and the nonclaim about XNU execution or retention.

probe_payload.py now saves the record using QEMU physical pmemsave before CPU
execution and after stopping. Four exact-image cases passed:

* Diagnostic image with synthetic runtime RAM: phase10, plus independent
  original diagnostic PID1 result1/cases205 and16KiB VM/4KiB hardware page log.
* Diagnostic image with stock placeholder RAM: phase254/detail0x208, no XNU entry.
* Explicit QEMU-only undefined instruction: phase255, ELR0x40083ffc,
  ESR0x02000000, exception EL1. A hardware breakpoint at loader_main redirects
  only the emulated PC to zero padding inside the owned Image; Image bytes are
  unchanged. This validates actual fatal-vector capture, not a physical fault.
* Complete32MiB recovery candidate: phase10 and the same independent PID1 proof.

The nine negative decoder checks also used the captured positive/refusal/
exception RAM records with a wrong expected identity, corrupted inverse or
truncated copy. Their rejection is host validation, not injected physical
device corruption. The QEMU machine exposes EL1 only; EL2 entry remains source
reviewed, not exercised by these tests. No physical-device commands were run.

Artifact hashes, exact reports and frozen kernel identity are retained in
trace-build5-evidence.json. Previous Image4 and recovery1 artifacts were preserved.
