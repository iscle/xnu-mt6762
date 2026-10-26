Physical storage admission cost
===============================

Capture31 (Image37/kernel52) reaches Apple launchd and spawns SpringBoard but
does not show a home screen. Its retained framebuffer is still the console.
The capture proves more than 17 minutes of execution; it does not measure CPU
utilization, per-sector latency, or the time spent inside individual drivers.
The physical MSDC reports 47,999,984 Hz. Firmware CPU clock decoding gives a
nominal CPU0 rate near 1.5 GHz, and this payload explicitly uses one core.

The two logs show a substantial startup difference, but are not a controlled
benchmark (different kernels, real hardware versus TCG, and different device
models). Launchd's timestamps are relative boot wall-clock observations:

============================  =======================  ======================
Event                         Physical capture31        QEMU kernel48
============================  =======================  ======================
SpringBoard spawned           01:01:59.787828            01:00:23.330699
SpringBoard exec uncorked      01:08:30.600519            01:01:42.351529
backboardd xpcproxy spawned    01:01:58.985023            01:00:21.114302
backboardd exec uncorked       not in retained log       01:03:19.051490
============================  =======================  ======================

The emulated run has a reviewed home-screen snapshot around 1,440 seconds;
that is the first reviewed positive snapshot, not a precise first-frame time.
At 1,800.008 seconds its model reports 1,554,328 CMD17 sector reads, 795,816,448
data bytes including the 512-byte EXT_CSD, and no backend errors. The laboratory
admission path checks GIC state and skips all physical pad, clock and rail
checks. Consequently it does not model the overhead below.

Two concrete source costs
-------------------------

``bsd/dev/mt6762_msdc_bsd.c:disk_strategy`` advertises/accepts up to 128 KiB,
then calls the synchronous, mutex-serialized transport separately for every
512-byte sector. There is no media cache or read-ahead inside this adapter;
this does not establish the state of APFS/VFS caches above it. The protocol
uses CMD13, CMD17, CMD13, draining the FIFO in eight 64-byte chunks. It does
not use multi-block commands or DMA.

``mt6762_msdc_protocol.h`` invokes ``quiet`` seven times per successful sector:
twice for each CMD13 and three times for the data transfer. Previously every
``quiet`` called the full physical ``admit`` implementation. On its successful
path, each admission performed 86 direct clock/pad/tuning/GIC MMIO reads and
ten synchronous PWRAP/PMIC reads. Therefore one sector required 70 PMIC reads;
a 128 KiB BSD request required 17,920. This excludes the wrapper's own status
reads and command/clear writes. Each MMIO read in the MSDC consumer includes
``dsb oshld``. These counts follow directly from the code, not measured timing.

Also, ``GenericARMCPU::start`` zero-initializes ``ml_processor_info_t`` without
setting ``powergate_latency``. ``ml_processor_register`` converts this zero to
``cpu_idle_latency``; ``ml_delay_should_spin`` returns false for zero. Thus
``delay_for_interval(1, NSEC_PER_USEC)`` in MSDC and ``delay(10)`` in PWRAP can
call ``assert_wait_deadline``/``thread_block`` whenever interrupts/preemption
are enabled. A requested microsecond delay can yield to other work while the
transport mutex remains held. This is a source-derived scheduling path; the
capture has no measurements of the number or duration of such deschedulings.

The MSDC wrapper now waits for its short interval using ``mach_absolute_time``
and ARM ``YIELD``. Interrupts and preemption remain enabled. It deliberately
does not call ``machine_delay_until``, whose ARM implementation uses ``WFE``
and can wait for an event. The protocol's error/deadline/iteration checks are
unchanged. The parent task separately added ``pwrap_wacs_delay`` in
``bsd/dev/mt6762_power.c``: WACS pauses of at most 10 microseconds use the same
timer/YIELD approach, while longer pauses and the separate ADC/thermal waits
retain their prior delay semantics. WACS register validation and transaction
timeouts are unchanged. ``hardware/power/test_wacs_delay.py`` compiles that
actual wrapper against a 13 MHz mock timer, including zero, wrap and long-delay
fallback cases.

Bounded static observations
---------------------------

``mt6762_msdc_admission.h`` moves only pad, preserved tuning and twice-read
PMIC status observations into a bounded reuse window. It does not grant
ownership. The exact original platform, clock and GIC checks still surround
every admission; all controller/DMA/CQE/card checks remain in the unchanged
protocol. Only the existing exclusive synchronous inherited-LK producer
contract enables this physical path.

An observation may be reused only while less than 1,000 microseconds have
elapsed since the BEGINNING of its full admission, and for at most 256
completed sectors. Both bounds apply; neither is an electrical guarantee.
The beginning timestamp makes a slow full check consume its own reuse budget.
A full check taking at least 1 ms still admits the immediately observed state
but grants no reusable window. Time reversal, any admission error, any sector
protocol error, and initialization/publication boundaries invalidate reuse.
An expiry encountered during an admission causes a new full observation at the
next admission. Scheduling during the first cheap checks is accounted for
before deciding whether to reuse. Scheduling during the last cheap checks
invalidates an expired window before it can be reused again.

The single transport owner is serialized by ``msdc_bsd_lock``. The window may
span consecutive calls, including calls from different threads under that
same lock; it is not an assertion that a complete 128 KiB request is atomic.
The PMIC fields are digital configuration/enable readbacks, not measured rail
voltages. An autonomous secure-firmware pad or rail change can remain unseen
until the next full pass. No observed snapshot, including the previous
twice-read policy, proves continuous voltage or secure-world ownership.
The explicit 1 ms/128 KiB policy is an implementation bound, not a recovered
hardware timing requirement. No PLL, voltage, tuning, bus-mode or DMA writes
are introduced by this change.

Counters and validation
-----------------------

``MT6762_MSDC_ADMISSION`` logs the policy. ``MT6762_MSDC_PERF`` reports after
the first completed sector, no more than once per 30 seconds of subsequent
read activity, and on an error. Counters are cumulative:

* ``sectors``/``bytes`` count successful media reads, excluding EXT_CSD.
* ``wall_us`` is elapsed wall time since the first media read.
* ``read_us``/``read_max_us`` include all time inside the serialized sector
  operation, including descheduling; they exclude waiting to acquire the BSD
  lock and the diagnostic print after the operation.
* ``admissions``/``full``/``reused`` count physical admission paths; they include
  initialization. The lab bypass does not increment these physical counters.
* ``full_us``/``full_max_us`` time full admissions including dynamic checks;
  ``slow_full`` counts those at least 1 ms, which cannot grant reuse.
* ``admission_errors`` and ``clock_reverse`` identify rejected observation
  paths. Protocol errors also invalidate reuse and use the existing terminal
  error log.

These metrics distinguish a useful observation window from one defeated by
expensive full checks. No speedup on the phone is claimed before these fields
are captured. A synthetic protocol-integrated test confirms seven dynamic
admissions, three commands and unchanged data while a fast modeled sector
needs ten PMIC observations instead of seventy. Tests cover all seven failure
positions before/after a cached observation, unchanged failed output, terminal
MMIO silence, exact expiry, slow observation, scheduling gaps, timer reversal
and the sector cap with a stopped mock timer. A separate test compiles the
actual native poll-delay function, replacing only ARM YIELD and the timer
functions, and checks zero delay, normal expiry, descheduling and counter wrap.

Run ``sh tools/mt6762/hardware/storage/test.sh``. Artifact and source hashes are
in ``admission-performance-evidence.json``. Kernel headers, builders, physical
catalogs and phone partitions are outside this change.
