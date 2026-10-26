Inherited battery publication after capture44
=============================================

Capture44 is the physical Image47/kernel57 run. Its ordered kernel log SHA-256
is 4eb9b9fb33eca61b4e852a257ac17160e117646c6e6140711fca13fd51279f2d;
Image47 physical-manifest.json SHA-256 is
a148bde845928f7088d0cb07758693cda8d30c311cf2513a62e021b11e264bd0.
``audit_battery_capture44.py`` regenerates the retained, source-bound record
``evidence/battery-capture44-observer.json`` without accessing the phone.
The unavailable native REA engine was not retried: this audit reuses exact-stock
protocol replay/disassembly, source and the explicitly selected retained capture.

Observed failure and its meaning
-------------------------------

Both PSC samples completed with ID f0, control f8 and status 10. The recovered
PSC5425E interpretation is CE_N=0 and STAT=1 (charging). This is the charger's
reported state, not a measurement of battery current or transferred energy.
The inherited charge configuration was not changed by this diagnostic image.
All twelve Apple-userland battery probes saw IOPS count 0, power_valid 0,
gauge current/charge invalid and zero voltage requests. Two passive ADC passes
completed, but their result words are historical until a new conversion is
proved. This capture does not establish a hardware charging failure.

The source explains the publication gap. Image47 enabled the six-read charger
probe, not an ongoing battery worker. The inherited branch returned after its
probes and key setup. No native battery sample reached HakiosBatteryReportPartial,
which instantiates the native service only for a nonempty valid sample.

Implemented consumer and producer contract
-----------------------------------------

``bsd/dev/mt6762_battery_observer.c`` is included by mt6762_power.c and remains
off by default. ``battery-inherited-observer=1`` selects a separate worker,
requires validated inherited read-only PWRAP and I2C5, and forbids normal ADC,
gauge or charger ownership grants and competing diagnostic modes. It skips
the old six-read PSC probe. The parent's I2C capability admits only repeating
one-byte reads of address 0x6a registers 3, 1, 0, at least 500 ms apart and with each
sample complete within 100 ms. The consumer sleeps 1000 ms after each complete
sample. No PSC write, charge enable/disable, limit, rail or ADC write is present.

Each acquisition obtains a two-second lease before I/O. PMIC 0x5730 is checked;
0x24 bit 2 supplies external power and enabled BATON 0xe08 bits 0/1 supply presence.
PSC ID is checked and STAT decoded only when fault/boost/OTG and contradictory
charging states are absent. Invalid status does not erase independently valid
PMIC presence. The published validity mask is normally 0x43 (presence, external,
status). Transport failure stops the whole observer; expiry never renews the
lease. Publication occurs after releasing its mutex, allowing the existing
IOKit publication and expiration machinery to operate independently of keys.

``fgauge-inherited-observer=1`` adds the optional gauge path. Its producer must
validate the actual live FDT with mt6762_gauge_baseline_from_fdt and provide:

* fgauge-baseline-version=1, fgauge-rfg=100, fgauge-car-tune=1000.
* fgauge-con0=0x129, fgauge-efuse-gain=0x416, fgauge-efuse-offset=1,
  fgauge-adjust-offset=0, fgauge-gain=0x416.

The kernel also requires the inherited wrapper profile and rechecks HWCID 0x5730,
clock 0xc0c=4, those five words and latch0xd0a=0 before and after every sample.
The coefficients reproduce exact-stock fresh initialization, not an unknown
historical Android object. Hardware shadow checks do not claim independent
absolute current calibration; logs explicitly retain absolute_calibration=0.

Only the currently admitted local gauge context can use a private PWRAP
exception. It has at most four attempted writes, exactly 0xd0a values 1, 9, 8, 0,
using the unchanged stock-derived gauge protocol. Public PWRAP writes remain
blocked. A failed transfer, changed configuration, stale NTER or malformed
handshake closes the gauge path permanently for the boot. No guessed cleanup
write follows an uncertain latch transaction. Protocol/configuration failure
may leave ordinary PMIC/PSC observation running; a PWRAP transport failure
stops both. Logs retain attempted/completed writes and observed latch idle.

The first complete latch establishes a 33-bit NTER baseline. Only a later
forward NTER sample publishes CURRENT (mask 0x4b); equality, backwards movement
and half-range ambiguity reject, while modulo wrap works. Signed current and
CAR share the same capture and lease. Current becomes native IOKit Amperage;
the existing gauge getter/sysctls receive current and signed charge through a
C-only bridge, without changing headers, IIG inputs or ABI layout. An active
but unmeasured/expired observer returns EAGAIN and cannot fall back to an
unrelated legacy cache. CAR remains accumulated signed charge, never remaining
capacity. The legacy gauge diagnostic sample/error counters still describe
its old worker; the inherited observer's counters and failure causes are in
MT6762_GAUGE_OBSERVER/STOP records.

Stable admission markers are::

  MT6762_BATTERY_OBSERVER_READY readonly_charger=1 interval_ms=1000 expiry_ms=2000
  MT6762_GAUGE_OBSERVER_READY max_writes_per_sample=4

Validation and physical boundary
--------------------------------

The host integration compiles the actual observer, public PWRAP guards and
gauge getter bridge with unchanged gauge/PSC/WACS protocols. It injects 272
PWRAP failures across both samples, 16 configuration changes, 70 acquisition
expiry positions, all PSC failures, status contradictions, unavailable grants,
clock overflow/reversal, early polling, stationary/backward/wrapped NTER,
partial latch handshakes and callback address/phase/budget/context misuse.
It checks exact write counts, terminal behavior, no cleanup, public-write
refusal, publication outside locks and expiration without a fresh read.
``test.sh`` includes this test and the parent's repeated PSC capability test;
the full power suite passed. These are controlled host models, not evidence
that the new observer has already run on the phone. Parent owns the kernel58
build, QEMU run and eventual physical trial.

Percentage and fresh ADC follow-up
----------------------------------

CurrentCapacity/MaxCapacity remain absent without SOC. The existing IOKit source
notes that powerd expects both to recognize a battery fully. Thus creating a
truthful partial HakiosBattery service may still leave an empty icon or no IOPS
entry. No percent, nominal capacity, 25 C temperature or SOC derived from CAR is
invented here; the UI is not claimed fixed by this observer alone.

The existing fresh ADC protocol provides a concrete next step: channel 1 writes
0x110e=2, requires observing READY clear then set at 0x108a, and scales the
15-bit result by 3*1800/32768 mV. It rejects missed generations, rails, timeout
and partial I/O. The inherited branch currently grants no such writes, and
normal adc-verified would require broad public PWRAP write ownership. A future
narrow private channel 1 capability can reuse that protocol with captured
configuration checks, serialization, a bounded lease and terminal failures;
voltage alone need not modify TDET. The raw captured ready output must not be
published as a fresh voltage. The 19-word passive ADC record contains actual
trim/config shadows but is not itself a verified conversion or a claim of
independent absolute calibration.

For a stock-derived initial SOC estimate, capture44's exact live gauge node
contains battery0_profile_t0..t5 and TEMPERATURE_T0..T5=50,25,10,0,-6,-10.
Every table advertises num=100/col=3 but has 222 cells (74 triplets). T0..T2 start
[0,43814,750] and end [22000,34055,990]; T3..T5 differ in early charge entries.
The complete raw cells/hashes are retained in the evidence JSON. Do not silently
pad, ignore, or normalize this mismatch: replay the exact shipped table parser
and selected battery/temperature branches first. The chosen loader strings
atag,fg_swocv_v=42185 and atag,fg_swocv_i=-5814 are boot observations, not current
native measurements. A fresh voltage, current/temperature compensation and
source-bound curve selection can underpin a clearly estimated initial percent;
loaded/charging voltage must not be mislabeled rested OCV. Paired NTC/BIF still
requires its separate exact TDET/configuration contract documented in GAUGE.rst.
Temperature validity and charging control remain separate from this observer.
