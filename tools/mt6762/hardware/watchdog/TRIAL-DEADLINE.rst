Opt-in inherited-watchdog trial deadline
=======================================

The boot argument ``mt6762_trial_seconds=60`` (decimal60..1800) stops this
kernel's AP watchdog refresh worker after the requested elapsed duration.
Absent, zero, malformed or out-of-range arguments leave the deadline disabled.
Large numbers are parsed as bounded decimal strings, not truncated integers.
This option requires the existing ``watchdog-refresh-owned`` handoff and exact
inherited admission: MODE0x7d, LENGTH field0xf000, REQ_MODE0x3f0036 and
REQ_IRQ_EN0x3b0034. It cannot turn on or reconfigure a disabled watchdog.

The implementation is in bsd/dev/mt6762_platform.c, not a separate watchdog.c.
Its deadline starts with the timestamp sampled for the first admitted
RESTART attempt. Later refreshes do not extend it. The existing configuration
and maximum10second scheduling-gap checks run first and retain their existing
failure behavior. A normal deadline expiry records its observations, performs
bounded cache maintenance and terminates this native refresh worker.
It does not perform a final extra kick, restart that worker, call loader_return,
change interrupt routing, enable DDR reserve or issue a software reset.
No physical trial of this new option is claimed here.

The exact inherited mode enables IRQ and dual mode. The programmed interval
is nominal30seconds from the last refresh, not a guaranteed reset deadline.
Secure handlers, other refreshers, clock acceptance and second-stage timing
remain uncharacterized. Arm the host capture before expiry, then measure actual
USB reappearance. A second unobserved normal boot can overwrite evidence or
restart the same bounded trial. There is no persistent boot-selector change.

Evidence delivery and concurrency
---------------------------------

At expiry the global128-byte ``mt6762_trial_record`` contains magicMTKTRIAL,
version1, requested seconds, attempt count, first/last/expiry timestamps in
uptime nanoseconds, raw MODE/LENGTH/STATUS/NONRST/NONRST2/REQ_MODE/REQ_IRQ_EN,
and before/after log lengths. Its layout is in trial_deadline.h. State0 means
disabled,1 armed,2 expiry reached,3 cache-clean operations completed. State2
is cleaned before the log flush; state3 is cleaned afterward. A state3 record
does not prove reset, cache survival or log consistency. Retrieval must bind
the symbol/address to the exact selected kernel and trial manifest, using the
separately verified same-build loader trace for build identity. Pin the record's
symbol VA from the frozen kernel's symbol table and derive its PA using that
trial's verified relocation; never guess its placement from another build.
This ordinary record has no unique per-boot nonce and is not an attestation.

The MT6762-only helper in osfmk/arm64/loader_return.c cleans the complete
``sizeof(loader_log)`` allocation, currently1536KiB, irrespective of the mutable
length. It also cleans the actual length, ring position, wrapped/linear flags
and loader_live descriptor, then executes DSB SY. The record is separately
cleaned and ordered. It uses64-byte lines, appropriate to the admitted Cortex-A53.
Range arithmetic rejects overflow; no mutable length can enlarge the range.

Logging continues. The helper does not acquire loader_log_lock, disable local
interrupts, copy/linearize the ring or modify its metadata. Existing log writers
have a bounded-spin path which can bypass that lock during a panic; holding it
over a full cache clean would delay writers without guaranteeing exclusion.
The clean is therefore explicitly best-effort. Flag1 always records possible
concurrent/post-clean writes. Flag2 additionally records an observed length
larger than the allocation; such a value is never used for cache traversal.
The two length observations can differ, and ring metadata need not describe
one atomic instant. A valid deadline line/record is positive evidence; absent
or partial evidence remains inconclusive.

MODE0x7d leaves DDR-reserve bit7 clear. Capture30's preloader log says DDR reserve
was not enabled, despite successful recovery of some XNU bytes. Cache cleaning
does not preserve DRAM through resets, DRAM training, bootloader overwrites or
subsequent DA allocations. Keep the existing separately verified DA heap
reservation and read evidence promptly; never advertise guaranteed retention.

Validation
----------

``bash tools/mt6762/hardware/watchdog/test.sh`` checks decimal admission,
unterminated/overflow inputs, first-feed anchoring, exact expiry boundaries,
irreversible expiry and bounded aligned cache traversal including pointer
overflow. It also compiles the actual worker/init source into a host harness
with deterministic time and MMIO:12 executions cover default/zero/invalid
arguments,60/1800second expiry and unchanged profile/scheduling failures.
Every modeled peripheral store must remain32-bit RESTART0x1971 at0x10007008.
Only ARM cache/barrier instructions are elided in that host harness; it does
not test real watchdog reload, interrupts, reset timing or retained memory.
