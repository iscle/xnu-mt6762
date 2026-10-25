Confirmed physical XNU execution, Image6
=======================================

Capture7 recovered the Image6 identity and loader phase10, immediately before
branch to XNU. The later read-only DA session recovered the exact kernel entry
page, boot arguments, initialized XNU memory globals and2936 bytes of its kernel
log. Symbol addresses came from the frozen kernel23 Mach-O; the log allocation
was within the loader-zeroed BSS. These observations establish physical XNU
execution, independently of the loader-only phase decoder.

The log reports16KiB VM pages,4KiB hardware pages, TCR_EL1=0x22a51a251a, custom
GICv3 initialization and substantial BSD initialization through the root-device
configuration call. The last retained line is cpu_start() cpu:0. IRQ and timer
entry counters both retain1; scheduler tick retains207. The root device and
mount-attempt count remain unset in the captured bytes. These are retained
lower bounds, not proof of the exact stop: dirty cached tail data may have
been lost across reset. Diagnostic PID1 and original Apple userspace on the
phone are not yet proved.

The boot arguments have no Video framebuffer. The loader's optional readback
validator therefore did not admit inherited scanout. This accounts for serial
selection and is consistent with the observed black screen; it does not prove
which scanout prerequisite failed. Native display ownership remains absent.

The virtual timer's13MHz identity and PPI27 match the actual stock DT. One
source discrepancy warrants a controlled regression: the GIC handler writes
EOIR without DIR, but initialization never established combined EOImode0.
A split-mode inherited interface would require separate deactivation. This is
a candidate explanation, not a measurement of the phone's inherited mode.
See Arm IHI0069H.b section4.1 and ICC_CTLR_EL1 in the official specification:
https://documentation-service.arm.com/static/67eaa4d098aa3c3b6eea7351
No clock, timer PPI, PMIC or interrupt-routing change follows from these logs.

Hashes, addresses and bounded capture evidence are in trace-build6-evidence.json.
The raw firmware, kernel and device captures remain private. No stock restore,
partition write or reset was performed during these readbacks.
