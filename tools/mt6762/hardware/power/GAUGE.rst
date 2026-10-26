MT6357 current/Coulomb observation and temperature prerequisites
===============================================================

The native gauge driver observes coherent current and signed accumulated charge.
It does not initialize or reset
an inherited gauge, enable charging, estimate remaining capacity, or report SOC.
Its hardware path has only been exercised against an explicitly synthetic QEMU
fixture. Physical calibration and ownership are still prerequisites.

Exact stock evidence
--------------------

The reference Image SHA-256 is
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
The modern driver in this Image differs from the older BSP gauge implementation;
the native latch protocol follows the Image. Relevant entry points are:

* pre_gauge_update: 0xffffff8008a84e08.
* post_gauge_update: 0xffffff8008a84ed0.
* instant_current: 0xffffff8008a85000.
* coulomb_get: 0xffffff8008a85344.
* reg_to_current: 0xffffff8008a863d0.
* battery_current_get: 0xffffff8008a86e8c.

Current is PMIC register 0x0d8a. Its signed encoding is one's complement,
including negative zero at 0xffff. The magnitude becomes stock 0.1 mA units
through integer magnitude * 314331 / 100000, then * 100 / R_FG, then
* CAR_TUNE / 1000, with truncation at each step. Positive means charging.
Native microamps are that result times 100. Wider intermediates prevent host
integer overflow; invalid inputs or unrepresentable results are rejected.

Coulomb raw registers 0x0d12/0x0d14 contain a signed 20-bit count:
(low >> 11) | ((high & 0x7fff) << 5), with sign high bit 15. Stock conversion
uses 11176 and rounds before R_FG/CAR_TUNE scaling. The decoder now feeds a private native current/charge snapshot, but a cumulative
gauge count is not a battery remaining-capacity measurement and is not published
as one. Neither its arbitrary inherited origin nor a learned full-charge
capacity is inferred from a counter reading.

emulate_stock_gauge.py executes these original ARM64 arithmetic routines with
mocked register reads and no device I/O. evidence/stock-gauge-vectors.json
contains 21 independently executed vectors spanning both signs, negative zero,
large raw values and three explicit R_FG/CAR_TUNE configurations. Host native
conversion tests compare against these vectors.

Configured values versus live calibration
-----------------------------------------

The exact DT has R_FG_VALUE=10 and CAR_TUNE_VALUE=100. The parser applies
multipliers 10 to both, producing R_FG=100 and CAR_TUNE=1000. Historical stock
battery-overcurrent initialization logs independently contain r_fg=100,
car_tune=1000, DEFAULT_RFG=100 and UNIT_FGCURRENT=314331. This is evidence about
the captured stock run, not a permitted runtime fallback.

The passive sysfs r_fg_value=100 reads active gauge-object offset +0x110.
However, car_tune_value=0 DOES NOT mean active CAR_TUNE=0. Its descriptor at
0xffffff8009887918 uses property 0x32 and info_get (0xffffff8008a85cd8), which
reads object +0x11c, a manufacturing calibration result. instant_current uses
active coefficient +0x114. Writing car_tune_value invokes calibration; no such
write was made. Reconstructing a historical Android object would require its
active value. A fresh native initialization can instead reproduce the exact
stock startup configuration from validated, present live DT cells; see
``GAUGE-BASELINE.rst`` and its original-code replay. That separate validator
returns 100/1000 only for the captured board profile and has no default
fallback, hardware admission or ownership side effect.

Inherited hardware configuration is separately checked before and after every
snapshot: FGADC_CON0 0x0d08, efuse gain/offset shadows 0x0c8e/0x0c90, manual
offset adjustment 0x0d94 and gain 0x0d96. The continuously adjusted active
hardware offset at 0x0d92 is not assumed constant. Analog gain, offset and
hardware autocalibration already affect the raw measurement; they must not be
applied a second time as invented software coefficients. No gain, offset,
clock, autocalibration, reset, ZCV, or overcurrent threshold write is present.

Handoff and bounded native protocol
-----------------------------------

In addition to the common native platform and verified PWRAP contract, the
handoff requires fgauge-owned=1 and fgauge-calibration-verified=1, plus actual
validated values for fgauge-rfg, fgauge-car-tune, fgauge-con0,
fgauge-efuse-gain, fgauge-efuse-offset, fgauge-adjust-offset and fgauge-gain.
These flags cannot substitute for establishing exclusive ownership of the
firmware's gauge traffic and verifying live hardware configuration.

PMIC ID must match MT6357, FG_ON at 0x0d08 bit 0 must be set, and analog/digital
clock gates 0x0c0c bits 3/4 must be clear. The driver rejects an inherited latch,
command or reset field in 0x0d0a before writing anything. After READ_PRE bit 0,
it polls LATCHDATA_ST bit 15 with a bounded deadline, captures current, CAR and
33-bit NTER at 0x0d20/22/24, and performs the exact post sequence: set CLEAR
bit 3 while READ_PRE remains set, clear READ_PRE, observe latch deassertion,
then clear CLEAR and verify the original idle control word. Only completed
snapshots are exposed. A transport or protocol fault is sticky; speculative
cleanup/reset writes and automatic retry after a fault are deliberately absent.

The first snapshot establishes a counter baseline. A later advancing NTER is
required before current and charge are valid. Equality invalidates both; backwards or
ambiguous half-range movement is rejected, and modulo-33-bit forward wrap is
supported. The actual MT6357 NTER period has not been independently recovered;
no native conversion to elapsed seconds assumes one. Sample validity expires
two seconds after acquisition begins, before configuration or latch I/O, using
the kernel's independent monotonic clock. A completed but already expired
acquisition is discarded. Getter validity and values check this deadline after
taking the mutex, so lock contention cannot make a stale snapshot look fresh.
The separate synthetic fixture
uses an explicit 2 Hz test clock, not a claim about actual hardware timing.

kern.redwood.mt6762_gauge_current_ua returns INT_MIN when invalid. Companion
nodes current_valid, samples, errors, fault and raw_current expose observation
state. ``mt6762_gauge_charge_uah`` is a signed 64-bit sysctl, with INT64_MIN
when invalid; ``mt6762_gauge_charge_valid`` shares the same snapshot validity.
``mt6762_gauge_freshness_rejections`` counts nonadvancing NTER and acquisitions
that have expired before completion. Current and charge are decoded together
and installed under one mutex; a partial CAR read failure rejects the whole
snapshot. Separate sysctl calls are independent observations, not an atomic
public multi-field ABI. Only a fresh current value adds the existing native
battery CURRENT valid bit;
no userland ABI structure was enlarged. Failed reads clear valid publication.

Validation
----------

Run ``sh tools/mt6762/hardware/power/test.sh`` for native latch, conversion,
freshness and compensation tests. The QEMU source patch adds lab-gauge only
when lab-power is selected. Synthetic calibration is conspicuously named; the
fixture rejects reset/calibration writes and is absent by default. Its QTest
checks four-write latch sequencing, NTER progress, clock loss, stale latch,
request timeout, stuck release, calibration mismatch and stationary time.

Build15 native XNU tests used kernel SHA-256
ef175089615dbe3d82b1b25d03fef5b4455b26e0eb95835783c72e8b2cccfd1d.
Positive current was 31400 microamps from raw 100 with advancing NTER. All six
startup fault cases and three faults injected after a valid reading rejected
current. An inherited latch caused zero gauge commands. All eight emulated
CPUs and the input queue remained live. See evidence/native-gauge-build15.json.

Build24 adds ``test_gauge_observer.c``, compiling the actual native observer and
getter code against controlled PMIC/clock callbacks. It covers signed pairs,
zero, partial CAR I/O failure, calibration loss, counter stalls/backwards/wrap,
slow acquisition, deadline boundary, and expiration while waiting for a lock.
The unchanged conversion decoder still matches 21 original Image vectors.
The header inventory required by genuine IIG replay remains unchanged;
only the native C implementation and diagnostic readers were extended.

The optional QEMU ``lab-gauge-sample`` is an immutable unsigned 48-bit tuple:
current register in bits 15:0, CAR low in 31:16 and CAR high in 47:32. It requires
``lab-gauge``; omission retains the earlier +31.4mA/zero-CAR fixture. The tuple
is copied at READ_PRE into the modeled latch and reset preserves its configured
input. It is explicit synthetic data, not battery physics or physical evidence.
Native eight-core tests reproduce original-stock vectors +31400uA /
+35800uAh and -31400uA / -35800uAh. Six startup faults and the same six faults
after a valid reading invalidate both observations. See ``evidence/native-gauge-build24.json`` and
``evidence/native-gauge-build25.json`` for hashes and original Apple-userspace
results.

Build24 is retained as intermediate evidence. Review found that its deadline
helper sampled the clock a second time, allowing a preemption gap to extend
validity beyond acquisition_start + 2 seconds. Build25 uses an absolute interval
and checked addition to the recorded start; zero intervals and overflow reject
before any PMIC I/O. The actual-observer host test injects preemption during
interval conversion and checks overflow without issuing a transaction.

The corrected build25 kernel SHA-256 is
69770fa400f264d66b7b4b83f102b05027222dc4d76814e50feae8bfd08c4a6a.
Its fresh native eight-core suite passed both signed vectors and all twelve
startup/post-valid fault runs with 16KiB software VM and 4KiB hardware pages.
A 150-second original Apple-userland run produced 100 IOKit/probe observations:
66 coherent +31mA / +35800uAh observations, then 34 with current and CAR invalid
after an explicit synthetic gauge-clock loss. IOKit removed Amperage and
InstantAmperage; all capacity, temperature, cycle and remaining-time properties
stayed absent. The reader is source-built; Apple executables were not rebuilt.
``check_gauge_probe.py`` reproduces these assertions from the retained serial log.
The kernel links and the replay/source guards pass; the full build still has
the documented inherited post-link export failures. These laboratory results
do not establish physical gauge calibration or a charging policy.

Battery NTC: recovered arithmetic, incomplete hardware admission
--------------------------------------------------------------

The stock temperature_get function returns a constant 25 C and is unsuitable
for battery protection. The genuine arithmetic path is force_get_tbat_internal
at 0xffffff8008a7be28, BattVoltToTemp at 0xffffff8008a7bbfc, and
BattThermistorConverTemp at 0xffffff8008a7bac0. The last uses the 21-entry nominal
table at 0xffffff800987b7d8. The current bytecode reads runtime configuration,
not merely the defaults of the older BSP.

The DT supplies COM_FG_METER_RESISTANCE=100 (multiplier 1) and COM_R_FG_VALUE=0
(multiplier 10). Their runtime object fields are +0xa14/+0xa1c. Flag
no_bat_temp_compensate at +0x82c4 suppresses only the first term; the second
remains, even though the flag's name may suggest otherwise. That flag's actual
runtime setting and the selected live table still need handoff verification.
The parsed numerical resistance parameters must not be mislabeled as directly
measured physical ohms.

Stock truncates absolute current to whole mA, multiplies by the sum of those
terms and divides by 10000 to get a millivolt correction. Charging subtracts
it from both NTC voltage and measured BIF voltage; discharge adds it to both.
Divider resistance then equals pullup_ohms * corrected_ntc_mv /
(corrected_bif_mv - corrected_ntc_mv). The exact Image's BattVoltToTemp has no
additional BIF resistor subtraction. It falls back to configured pullup voltage
only on explicit unsupported-property return -524; other error handling in
that path is not suitable to copy into a protection driver.

thermistor.c now provides a pure compensated converter, validated against 20
executions of the original ARM64 prefix and converter in
emulate_stock_ntc.py / evidence/stock-ntc-vectors.json. Invalid rails and values
outside the nominal table are rejected rather than clamped to plausible
readings. This function does not establish physical calibration or freshness
and has not been connected as a valid native battery temperature provider.

BIF measurement side effect and remaining contract
-------------------------------------------------

Stock bif_voltage_get is 0xffffff8008a87694. Its AUXADC channel descriptor uses
hardware channel 11: request 0x110e bit 11, output 0x109e ready bit 15 and
12-bit data scaled raw*1800/4096. Before conversion, mt6357_vbif_conv at
0xffffff8008b6b3a0 clears PMIC 0x1236 bit 1 (BATON_TDET_EN). Afterward it sets
that bit unconditionally. It does not restore the exact inherited state.
Consequently adding BIF to the existing generic ADC request list would silently
change battery detection configuration and is not permitted by adc-verified.

A native implementation needs a separate exclusive BATON/TDET ownership
contract, confirmed initialized channel/mux/trim configuration, and exact
save/change/readback/restore/readback of the affected bit around a serialized
bounded conversion. PWRAP failure can prevent restoration; the physical entry
contract must provide an independent safe fallback and invalidate protection
readiness in that case. Neither a laboratory flag nor historical state proves
such a physical fallback exists. No BIF/TDET write has been issued here.

The stock processed ADC path at 0xffffff8008b6b8fc applies per-channel ratio
and resolution. Its battery-temperature cali hook 0xffffff8008b6b3fc performs
jump/low-voltage diagnostics and rereads; it is not a recovered factory gain
coefficient. The debug path can reset AUXADC after abnormal readings, which
must not be inherited as silent recovery. General hardware ADC trim shadows
and channel setup require live handoff verification; no guessed software
trim has been added. Calibrated paired NTC/BIF samples, fresh calibrated
current, verified board/table/pullup configuration, open/short handling, and
independent temperature validation remain prerequisites for charging enable.
