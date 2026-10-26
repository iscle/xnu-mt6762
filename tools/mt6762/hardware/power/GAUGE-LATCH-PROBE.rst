Finite inherited gauge diagnostic in the HakiOS tree
===================================================

This ports the tested kernel55 passive ADC extension and completes the finite
gauge diagnostic left unfinished at the old-tree checkpoint ``2d16066b``.
It adds no normal gauge worker, battery/SOC publication, ADC request, charger
write, clock/rail initialization, or general PWRAP ownership. The public
``mt6762_pwrap_write16`` interface and production gauge protocol are unchanged.
The code is host-tested; no new physical probe has been enabled or executed.

Passive observation
-------------------

The original ``MT6762_PMIC_ENTRY`` version 1 format and two 13-word passes stay
unchanged. After both complete, a separate ``MT6762_ADC_ENTRY`` version 1 record
contains two 19-word passes: HWCID followed by SWCID and the 17 native BIF/ADC
configuration words. This adds at most 38 ordinary reads. Wrong PMIC family or
any transport failure stops the current pass without publishing its partial
contents. There is no conversion request, latch command, reset, trim or TDET
write. The new source audit verifies every address/name against the actual
MT6357 BSP register header and the native BIF inventory.

Capture33–36 logs each contain two complete 13-word PMIC sets. Timestamped log
replays are deduplicated by pass/index/address/value, never counted as extra
observations. All four contain the same admission configuration: HWCID 5730,
clock 0c0c=0004, CON0=0129, efuse gain 0416, efuse offset 0001, manual adjustment 0,
hardware gain 0416, and latch 0. BATON remains 0005 and TDET 0. Their ADC words
differ, but no capture contains the new ADC configuration record or a requested
conversion. Those old ADC values remain stale evidence, not fresh measurements.
Capture35/36 share a retained trace hash; these records do not prove independent
firmware ownership or complete DRAM retention. The source-bound ledger in
``evidence/gauge-latch-review.json`` preserves each log and trace identity.

Admission contract
------------------

``fgauge-latch-probe=1`` is a distinct request, default absent/off. It is only
called in the existing ``pwrap-inherited-probe`` branch. Require all of:

* Initialized, unfaulted, read-only PWRAP using the exact LK22 profile.
* No active ADC, charger observer or charger owner in this driver.
* Handoff ``pwrap-inherited-probe=1``, ``fgauge-baseline-version=1``,
  ``fgauge-rfg=100`` and ``fgauge-car-tune=1000``. The producer must derive the
  latter pair through the existing exact live-FDT validator, not defaults.
* Five explicit properties: ``fgauge-con0=0129``,
  ``fgauge-efuse-gain=0416``, ``fgauge-efuse-offset=1``,
  ``fgauge-adjust-offset=0`` and ``fgauge-gain=0416``.
* No ``fgauge-owned``, ``fgauge-calibration-verified``, ``adc-verified``,
  ``charger-verified``, ``charger-control-owned``, ``pwrap-write-owned`` or
  ``lab-fixture`` grant. Missing required fields and different values reject.

The kernel rechecks exact HWCID, clock word, all five configuration words and
idle latch before and after each capture. ``GAUGE-BASELINE.rst`` and the saved
original-code replay establish fresh startup coefficients 100/1000 from actual
DT cells 10/100 and their multiplier 10. They do not recover an old mutable
Android gauge object or establish absolute electrical calibration. Hardware
gain/offset already affect the raw readings and are not applied a second time.

Finite transaction and failure behavior
--------------------------------------

The unchanged ``mt6762_gauge_capture`` implements the exact modern stock
sequence recovered from Image SHA-256
``82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b``:
READ_PRE 1, read READY and six current/CAR/NTER words, CLEAR+READ_PRE 9,
CLEAR 8, wait READY low, zero, then verify zero. Its source locations and
instructions are retained in ``evidence/gauge-protocol-disassembly.txt``;
the older BSP's gauge implementation is not substituted for that sequence.

A private callback permits only address 0d0a and values 1,9,8,0, in order,
twice. Each write consumes its slot before WACS starts, including a failed or
ambiguous transaction. There are at most eight attempted writes per boot, no
retry, and no ninth write through cleanup. Latch data reads are allowed only
after the current sample's READ_PRE and before release. The callback holds
``pwrap_mutex`` for the actual unchanged WACS transaction and checks readiness,
fault, private budget and time after taking the lock. Public writes are still
refused throughout the diagnostic.

Each sample has a two-second acquisition lease beginning before configuration
reads. Time is checked both before and after each transaction; a late
completion supplies no valid result or permission for the next write. Clock
regression, overflow, lock wait and scheduling delay cannot renew the lease.
The second acquisition starts at least one second after completion of the
first. Only forward modulo 33-bit NTER movement below half range passes. Equal,
backward and ambiguous half-range movement terminate without another attempt.

On success the protocol performs the complete release and verifies idle.
On handshake or transport failure it deliberately **does not invent cleanup**:
an uncertain latch or PWRAP transaction must not be cleared speculatively.
The last latch state may therefore remain 1,8001,8003 or 8008 in fault fixtures.
The capability closes permanently, and a second call in the same boot performs
no I/O. Transport failure also keeps the existing global PWRAP fault sticky.
``latch_idle_observed`` reports the last verified observation, invalidated by
a write attempt or uncertain transport; it is not a recovery guarantee or an
exclusion proof against another firmware master. ``cleanup_writes=0`` is
explicit in the terminal record. Parent-controlled reset/recovery remains the
route after an uncertain failed trial.

Logging and producer integration
-------------------------------

The stable kernel-presence marker remains::

  MT6762_GAUGE_LATCH_BEGIN samples=2 max_writes=8

Configuration records show the exact live words before/after each capture.
Write-result records show the admitted value, error, attempted and completed
counts; failed reads also produce a transport record. RAW retains current,
CAR-low/high and all three NTER words. SAMPLE records retain acquisition,
completion, expiry, coefficients and derived current/charge diagnostics.
The first sample has ``diagnostic_valid=0``; the second can become 1 only after
release, unchanged configuration, lease and advancing-NTER checks. A terminal
failure always has ``diagnostic_valid=0``. Neither result is a published battery
sample: every applicable record says ``measurement_published=0``,
``absolute_calibration=0`` and/or ``ownership_grant=0``.

No producer, loader or physical-grant change is part of this patch. A future
producer must request this flag separately, pass the exact validated baseline
and configuration, require the compiled marker, and retain the whole-trial
watchdog. The passive ADC extension can run alone without requesting the latch
probe. This is an evidence step toward real measurements and charging, not a
completed charging policy: external-master exclusion, a fresh ADC conversion,
temperature calibration/compensation, capacity/SOC and charger control remain.

Validation
----------

``sh tools/mt6762/hardware/power/test.sh`` includes the new tests and passes.
The integration harness compiles the actual included native probe, verbatim
public PWRAP guard and unchanged gauge/WACS protocols. Only MMIO, clocks,
mutexes, handoff and logging are modeled; no device is opened. It verifies:

* Two real protocol captures, eight writes, clean release, signed coefficient
  conversions, and no battery publication or public-write bypass.
* All 248 applicable failure positions/stages across the 64 successful WACS
  transactions: before command, response/completion, read-clear completion,
  and bounded timeout. A write may physically take effect before its failed
  acknowledgment; neither completion nor cleanup is then invented.
* All 32 before/after configuration-word changes, all 64 transaction-expiry
  positions, READY/release timeout, unexpected control/top bits and failed
  final-idle verification; no operation follows the terminal failure.
* Missing/wrong handoff fields, conflicts, wrapper/worker gates, stale and
  backward NTER, half-range ambiguity and valid rollover, lock/preemption
  expiry, overflow, early sample separation and private-callback misuse.
* Exhaustive 16-bit write-address and per-phase value rejection in the portable
  budget policy, along with pending/duplicate/out-of-order/ninth-write checks.

The passive ADC tests retain all 64 per-read failure cases across both original
and additional records, wrong-ID stops, raw zero/all-ones acceptance, and no
measurement/ownership grant. These are host fixtures, not physical calibration,
electrical ownership, full kernel execution, or proof that a phone trial will
succeed.

``audit_gauge_latch.py`` reproduces the capture/source ledger and scoped tests.
The optional ``--sanitize`` test mode currently cannot link on this host:
``libasan.so.8.0.0`` and ``libubsan.so.1.0.0`` are absent. The normal strict C
build/tests pass; no sanitizer result is claimed and no packages were installed.
