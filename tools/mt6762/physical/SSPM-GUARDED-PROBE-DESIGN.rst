Guarded SSPM read diagnostic: design only
========================================

A small, explicitly selected loader diagnostic can test whether particular
CSRAM/mailbox reads complete or raise a precise local synchronous abort. It
does not need to assume the five zero SECURITY_AO values are authoritative
permissions. This is a feasible next experiment with narrower consequences
than enabling the current 174-word native observer. It is not a guarantee
against interconnect hangs, asynchronous errors or firmware intervention.

This document proposes the implementation and validation boundary. No loader,
kernel, header, exception vector, device or firmware has been changed by this
review. Existing SSPM/DVFS handoff flags remain off.

Preferred placement
-------------------

Use a separate loader-only diagnostic mode after the existing CPU/FDT/entry
checks, before loading or entering XNU. Run it on the boot CPU with the current
loader stack, admitted MMU/cache-off state and existing DAIF policy. Secondary
CPUs are not started by this diagnostic. An explicit incompatible-mode check
must prevent this mode from also entering XNU or granting active SSPM access.

Keep the inherited watchdog configuration untouched. Commit the result to
owned retained RAM, print it only after the protected access has finished,
and stop without starting XNU. A watchdog reset may occur; neither its timing
nor retained RAM survival is guaranteed. This separates a possible delayed
error from normal desktop startup. Hardware recovery is not part of the read
primitive and must not write SSPM, PMIC, clock or permission registers.

Immediately recheck the already observed external clock/power profile before
each protected region: AXI0x10000040 source/gate mask0x83 equals1;
SSPM0x10000090 mask0x83 equals1; MCU_PM_BCLK bit17 at0x100010c8 clear;
MAINPLL words0x1000c23c/240/248 equal0xd4800181/0x81150000/0x80000001;
SYSRAM0x10006350 equals0xffff0000; SSPM SRAM0x10006358 mask0x10013 equals0x12.
The SRAM bit interpretation remains BSP-derived screening. Record the five
SECURITY_AO words as raw observations, not permission predicates. A trial can
be deliberately limited to capture33's all-zero view without claiming that
zero grants access. Any mismatch stops the experiment before protected reads.

The loader's existing raw accesses use the MMU-off regime. Arm documents
Device-nGnRnE data access attributes with stage1 disabled, and notes that stage2
can affect the effective regime. The inherited EL1 path deliberately does not
change EL2 state; do not infer that an EL2-routed fault is locally recoverable.
See `Arm memory attributes, section3.2
<https://documentation-service.arm.com/static/63a43e333f28e5456434e18b%3Ftoken%3D>`_.

Minimal exact read set
---------------------

Use only aligned single32-bit loads. Do not use memcpy, vector/multiple loads,
atomics, prefetches, pointer chasing, retries, command writes or ACK clears.
The first diagnostic reads these13 words twice, at most26 protected loads:

================ ====================================== =====================
Region           Exact physical addresses               Ordinary-read evidence
================ ====================================== =====================
CSRAM guards     0x00110c00,004,008,00c,0x00110ea0       Stock AP RAM repository
Mailbox0 slots   0x10450000,004,008,00c,010,014,018       Stock memcpy-from-SSPM
Mailbox0 OUT_IRQ 0x10451004                             Stock status load
================ ====================================== =====================

Suffixes in the table retain their region prefix: for example004 in mailbox
slots means0x10450004, and004 in CSRAM means0x00110c04. All widths are4.
Probe CSRAM first, mailbox data second, and OUT_IRQ last. On the first caught
abort, stop the entire protected-read sequence; preserve the successful prefix
and fault record, and perform no other SSPM read. No second pass is attempted
after a failed first pass. The second pass is stability evidence, not a retry.

Exact stock Image SHA256 is82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
``init_cpuhvfs_debug_repo`` at0xffffff8009619f00..9f78 initializes these guards
as ordinary repository RAM. ``sspm_mbox_read`` at0xffffff80088095b0..9614
selects slot*4, then calls the ordinary copy helper at0xffffff80088094a4.
PLATFORM/CPU descriptors at0xffffff8009846a70/6ac0 limit the selected data to
slots0..6. ``sspm_mbox_polling`` loads OUT_IRQ at0xffffff80088096dc, and clears
it with a separate store at0xffffff8008809704. The new diagnostic must perform
the load only. Per-span hashes already exist in
``hardware/cpu-power/evidence/sspm-observer-evidence.json``.

Exclude IN_IRQ0x10451000 from the first probe. The reviewed stock AP send path
writes that doorbell; the exact ordinary AP status read demonstrated here is
OUT_IRQ. Exclude mailbox2, SSPM GPRs, firmware/shared DRAM, PVT/state arrays
beyond the five guards, DEVAPC permission words and all other offsets. This is
a deliberate smaller set than the existing native observer, not a claim that
other ordinary words are necessarily unsafe.

Local fault recovery contract
-----------------------------

The existing ``physical_vectors`` send all16 vector entries to a fatal path;
they do not support recovery. A new private, temporary vector table or a
strictly gated EL1h synchronous veneer is required. A wrapper arms a
single-use RAM context containing the exact load PC, recovery PC, physical
address, destination and record index. Save/restore the previous VBAR_EL1;
do not alter firmware vectors or EL2/EL3 registers. Save every general register
the veneer clobbers, preserve stack alignment, and leave the existing x28 fatal
recursion guard semantics intact. The handler must not print or access MMIO.

Recover only if ALL these conditions match:

* The designated current-EL/SPx synchronous vector was taken at EL1h, with the
  same admitted boot CPU and a currently armed, unused context.
* ELR_EL1 is the one labelled ``ldr wN,[xAddress]`` instruction, not a nearby
  barrier, context store, return instruction or an arbitrary PC range.
* ESR_EL1.EC is0x25, IL is1, DFSC is0x10, and WnR/CM/S1PTW are all0.
* FnV is0 and FAR_EL1 exactly equals the selected aligned physical address.
* The address/index belongs to the fixed13-word whitelist and the recorded
  expected address matches the wrapper's armed context.

The syndrome meanings above are defined by `Arm ESR_EL1
<https://support.arm.com/documentation/111107/2026-09/AArch64-Registers/ESR-EL1--Exception-Syndrome-Register--EL1->`_.
Record raw ESR/FAR/ELR/SPSR, including implementation-defined external-abort
classification, rather than guessing the blocking device from the syndrome.

For a matching fault, mark the destination value invalid, disarm BEFORE return,
set ELR_EL1 to the fixed failure continuation, restore saved registers and
ERET with the saved SPSR. The wrapper returns an error without reexecuting the
load. The destination remains untouched on failure. Every nonmatching fault,
including nested faults and SError, goes to the existing fatal handling; do
not turn generic kernel/loader errors into apparent probe success.

Use a pre-load ordering barrier and a post-load completion barrier, but do not
include either in the recoverable PC match. Check a short overall elapsed
budget between loads, and record pre/post timestamps. That budget is only a
software dispatch bound: a stalled load or barrier cannot be interrupted by a
later timer check. Do not label it a hardware timeout.

Record pending/read-complete/fault states separately and commit inverse/check
fields last. A reset with a pending record means incomplete evidence, not a
confirmed abort. A proposed separate1024-byte record at0x40085400 would fit
after the existing peripheral record and before0x40090000, but requires linker,
reader, identity and DA reservation assertions; it is not allocated here.
Do not consume the six remaining catalog slots or reinterpret existing record
ABIs. All stores made by the probe itself are to this owned context/result RAM.

Interpretation and residual risks
--------------------------------

Classify results as ``completed_nonzero``, ``completed_zero``,
``synchronous_abort`` or ``incomplete``. Successful loads demonstrate that those
specific accesses completed in that execution state. A recognizable nonzero
guard pattern is stronger content evidence than zero, but the guards are AP
initialization, not proof of a running SSPM firmware. Cold-boot CSRAM may
legitimately be zero before Android writes the repository. Idle mailbox words
can also be zero. Therefore a read-only test cannot distinguish true zero
contents from RAZ without an independent known-value observation. Two equal
reads cannot resolve that ambiguity and do not form an atomic snapshot.

A synchronous abort establishes an access failure, not whether its cause was
permissions, power, address decode or a different bus error. A completed load
does not establish future access, reserved-memory preservation, firmware
identity, active traffic ownership, voltage readiness or permission to write.
No result automatically enables the full observer or active transport. A
successful subset can justify a separately reviewed expansion of the guarded
read set, without waiting for an authenticated security-register view.

The Cortex-A53 TRM warns that externally generated data-access errors can be
asynchronous (`Arm DDI0500J, section5.4
<https://documentation-service.arm.com/static/6040c321ee937942ba301626>`_).
Current loader entry masks asynchronous errors with DAIF.A. An error may
remain pending after a completed load; barriers and a successful ERET do not
prove its absence. Do not temporarily unmask and acknowledge it as if that
were a generic recovery procedure. Bus hangs, EL2/EL3 routing and platform
error latches are outside this local handler. The proposed loader-only ending
avoids deliberately handing such unknown state to a desktop kernel, but does
not make the hardware transaction universally recoverable.

Why not reuse a native XNU helper
--------------------------------

In this tree, ARM64 ``ml_probe_read`` and ``ml_probe_read_64`` in
``osfmk/arm64/loose_ends.c`` explicitly panic as unimplemented.
``ml_nofault_copy`` in ``machine_routines.c`` accepts valid RAM translations
and is not an MMIO external-abort catcher. ``sleh.c:handle_kernel_abort`` uses
copyio recovery for VM/alignment faults, while external-abort0x10 reaches the
unclassified-abort path and panics. Merely adding a copyio table entry will
not contain this case.

A later native implementation would need a dedicated exact-PC exception
hook, device-memory mapping, per-CPU/per-thread context with explicit nesting
and preemption rules, and the same syndrome/whitelist checks. That changes
global fault handling and requires separate validation. The current raw
``bsd/dev/mt6762_sspm.c:passive_read`` cannot be used as this guarded primitive.

Required offline validation before an image
------------------------------------------

Compile/disassemble the actual wrapper/vector code and verify a single32-bit
LDR at the recoverable PC, no target stores, no WFE/poll loop in the primitive,
and no callable unrestricted address path. Execute the real instructions in
an ARM64 fixture that models EL1 exception entry/ERET, injecting a synchronous
abort at every one of the26 possible loads. Check unchanged failed output,
valid successful prefixes, context disarming, exact return PC and register/
stack/VBAR/DAIF restoration. Negative cases must cover wrong PC/address/EL/
vector/DFSC, writes, FnV, table walks, cache maintenance and nested faults.
Model zero, nonzero, changing values, deadline expiry, a pending record, and a
permanently stalled access; the latter must remain explicitly uncontained.
Ordinary QEMU memory returning zero is not a physical permission test.
