Explicit GIC end-of-interrupt mode
=================================

The native GICv3 handler completes owned interrupts through ICC_EOIR1_EL1.
Before build28 it never established the CPU-interface EOImode, so a firmware
handoff with split mode could leave the interrupt active after its first
handler invocation. Arm IHI0069H.b section4.1 and ICC_CTLR_EL1 define bit1:
zero combines priority drop and deactivation; one requires a separate DIR.
Official reference:
https://documentation-service.arm.com/static/67eaa4d098aa3c3b6eea7351

Initialization now preserves other ICC_CTLR_EL1 bits, clears EOImode, executes
an ISB and verifies readback before enabling delivery. Failure to establish
the required mode panics instead of silently accepting a one-shot interrupt
path. Each CPU logs its before/after words. The completion path itself, timer
frequency, PPI number, clock configuration and routing remain unchanged.

The explicit QEMU-only prepare.py option --lab-split-eoi sets mode1 before
XNU, reads it back and prints the marker only if it was accepted. Without
that option the trampoline performs no GIC setup. The fixture is not part of
the physical loader or a claim about inherited phone state.

The eight-core regression reproduces failure with old kernel27 under mode1:
no diagnostic PID1 within the ten-second run. The same old kernel with the
otherwise identical combined-mode fixture starts all eight cores and reaches
PID1. Fixed kernel28 reads8c02 and
writes/reads8c00 on CPU0, starts all eight cores and reaches the diagnostic
input-queue userspace. The ordinary combined-mode regression also passes and
reports8c00 ->8c00 on all cores. The before/after experiment verifies the
software bug under the specified inherited state; it does not prove that
physical Image6 inherited mode1. Its retained timer entry count1 is consistent
with that hypothesis, but cache loss and other handoff gaps remain possible.

The exact new normal-boot image also passes its delivered-payload QEMU test,
including the205-case IIG diagnostic,16KiB VM/4KiB hardware mapping, and loader
phase10. Its32MiB boot partition was written and fully read back; para,
recovery,seccfg and vbmeta hashes stayed unchanged. At recording time the
physical restart of Image7 was pending. See gic-eoi-build28-evidence.json,
trace-build7-evidence.json and PHYSICAL-XNU-ENTRY.rst. No full iOS boot or
physical display/touch/charging readiness is claimed.
