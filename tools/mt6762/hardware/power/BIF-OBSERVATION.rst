Native paired ADC and raw trim observation
=========================================

Build27 adds a bounded diagnostic needed to investigate battery-temperature
calibration. It does not publish BAT_TEMP, implement a calibrated transfer
function, or enable charging. The physical trial still uses frozen kernel23;
this observer has only run in host tests and the explicit QEMU laboratory.

``bsd/dev/mt6762_bif_observer.c`` is included by ``mt6762_power.c`` so it shares
that driver's ADC mutex, PWRAP ownership and request-only write callback.
The existing versioned BIF admission and ten expected configuration words remain
required. Initialization, before this driver's worker and the gauge/thermal
workers start, reads two matching complete scans. Each later pair repeats the
scan before and after both independently fresh conversions under the ADC mutex.
Every scan must match the initialized baseline. Failed I/O or a changed word
invalidates the observation and latches the existing fault. Missed generation
retry still requires a complete matching post-scan and unchanged clear TDET.

The fixed observation set is twenty whole 16-bit words: HWID0x0008, SWCID0x000a,
TDET0x1236, the existing ten configuration registers, analog0x1008, and six
factory-shadow registers0x11a2..0x11ac. The extra raw fields have no guessed
expected defaults or interpreted coefficient values. A different but stable
inherited shadow is recorded verbatim. Full HW/SW identity is compared, rather
than checking only the HWID model byte. The added reads are direct register
accesses; they do not invoke the OTP/nvmem command interface.

The shadow/SWCID register addresses come from the supplied MT6357 register
header, not an observed physical read or recovered exact-kernel shadow read.
``NTC-TRIM.rst`` and ``NTC-TRIM-INIT.rst`` preserve that provenance and the
unresolved selector, coefficient, compensation and shadow-loading semantics.
Two matching scans cannot exclude ABA changes or an unobserved reset that
restores the same words. No hardware reset epoch is asserted. This is complete
only for the enumerated observation set, not complete physical calibration.
No calibration or TDET writes are added; the callback still permits only
channel3/channel11 ADC requests at0x110e.

Atomic diagnostic record
------------------------

Read-only ``kern.redwood.mt6762_bif_observation`` returns one72-byte native
little-endian record copied under the ADC mutex. It returns ENXIO when absent,
faulted, expired or older than the current clock. It initiates no PMIC access
and does not renew the observation. The existing scalar raw/fresh sysctls use
the same reader; separate sysctl calls still need not represent the same pair.

=================  ======  ================================================
Field              Offset  Type/meaning
=================  ======  ================================================
version            0       u32,1
size               4       u32,72
acquired_abs       8       u64, acquisition start in kernel absolute time
expires_abs        16      u64, at most acquisition start plus two seconds
pmic_id/swcid       24/26   u16, full observed identity words
TDET               28      u16, unchanged owned BATON/TDET word
NTC/BIF raw         30/32   u16, completed paired conversion counts
config             34      seventeen u16 raw words, order below
reserved           68      two zero u16 words
=================  ======  ================================================

Configuration order is10de,10e0,1120,1126,1128,112e,1132,1136,113a,113c,1008,
11a2,11a4,11a6,11a8,11aa,11ac. Preserve the full words; field masks do not
establish their calibration semantics. Version/size and timing are internal
engineering diagnostics; no Apple-facing battery structure or IIG input changed.

The lease starts before the first state scan. Checked absolute interval
addition handles zero/overflow; slow reads, interval-conversion preemption and
publication delay cannot extend it. Getters sample time after locking and reject
clock regression. A failed replacement immediately invalidates the old record.

Validation
----------

``test_bif_observer.c`` compiles the actual included consumer. It checks changes
to every one of the twenty words before/during a pair, failure at every I/O
position in initialization and a successful pair, unchanged output on failure,
sticky rejection, missed-generation retry, raw-value preservation, acquisition
age, expiry during lock wait, overflow, clock regression and write restrictions.
The complete power host suite also passes the existing charger/gauge/ADC and
original-stock arithmetic vectors.

Build27 kernel SHA256 is
0d2f6bf06c1d50aae5b326830c991ab8717847000354d60b648d553d7a5c29d6.
The source and IIG inputs stayed stable during linking. The full build still
fails the documented inherited post-link export checks; it is not fully green.
The eight-core QEMU run uses the explicit slower2000us ADC laboratory setting,
16KiB software VM and4KiB hardware pages. It yielded21 complete records from11
acquisitions. A separate post-fresh single-shadow change produced3 fresh records
then18 ENXIO results; no TDET or trim write was attempted. The startup existing
configuration-mismatch regression rejects before BIF conversions. These
results validate software/model behavior, not electrical calibration or the
physical phone. ``check_bif_observation.py`` checks the actual syscall records
against independently known model values and counters. Evidence and hashes are
in ``evidence/native-bif-build27.json``.
