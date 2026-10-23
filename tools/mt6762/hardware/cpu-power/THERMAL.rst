Native calibrated thermal observation
=====================================

This milestone adds PMIC die/buck temperature measurements and CPU sensor
register observations. It does not enable DVFS, charging, thermal trip writes,
sensor controller initialization, watchdog reset, or a cooling governor. No
physical phone has executed it. Battery NTC calibration is a separate problem;
PMIC die temperature cannot substitute for battery-cell temperature.

Evidence and calibration
------------------------

``evidence/stock-thermal.json`` contains bounded records from the exact Image
and original boot logs, with input SHA256 digests. Stock function addresses:

* CPU calibration decoder: 0xffffff80088888d4; room coefficients:
  0xffffff8008888b38; controller reader: 0xffffff80088892f0.
* PMIC calibration: 0xffffff800888a914 and 0xffffff800888abf0; die reader:
  0xffffff800888ae8c; buck readers: 0xffffff800888b0b4/0xffffff800888b304.
* Stock PMIC ADC descriptor table: 0xffffff8009105ef8, 12-byte entries.
* Stock thermal-controller mapping: 0xffffff8009852b10, 40-byte entries.

The provided BSP reference files are ``thermal/mt6765/src/mtk_tc.c``,
``mtk_pmic_efuse.c``, ``thermal/mt6765/inc/tscpu_settings.h``,
``include/mt-plat/mt6765/include/mach/upmu_hw.h`` beneath
``kernel-4.14/drivers/misc/mediatek``, and
``kernel-4.14/drivers/iio/adc/mt635x-auxadc.c``. Native code independently
implements recovered numerical/register contracts; BSP driver code is not
copied into XNU.

Actual stock DT replaces BSP get_devinfo calls with NVMEM: physical
0x11c50190..0x11c5019b contains three little-endian words in the order
temp1,temp0,temp2. Stock decoder disassembly at 0xffffff80088889c0 loads
that order and swaps temp0/temp1 for its log. Historical words are
0299546b/9d9d514c/a5d36940. They decode to calibration-enabled, GE630,
OE469, DEGC53 (half degrees), VTS332/340/332/331/330, slope0 and ID0.
Historical derived gain10288 and room coefficients8839/8857/8839/8836/8834
match the boot log. These historical values are test vectors, never runtime
fallbacks. Runtime reads both snapshots and rejects disagreement, disabled
calibration, out-of-range gain/offset/VTS and invalid DEGC. It rejects values
for which stock would substitute generic defaults.

PMIC efuse shadows are read twice through the already-owned PWRAP interface:

================= ===============================
Address           Fields
================= ===============================
11ae              DEGC[5:0], calibration-enable[8]
11b0              Die VTS[12:0]
11b2              Slope[5:0], slope-sign[8]
11b4              ID[4]; ID0 ignores slope
11b6              VCORE sensor VTS[12:0]
11b8              VPROC sensor VTS[12:0]
================= ===============================

Historical PMIC values are DEGC55, VTS1588/1526/1534, ID0 and slope0.
The boot log independently records intercepts442134/387134/389282 and
denominators-1681/-1863/-1863. Integer ADC scaling to mV happens before
temperature scaling, matching stock. The recovered stock formula uses
``factor +/- slope`` for the measurement denominator but
``factor +/- 10*slope`` for the intercept denominator; these are intentionally
distinct. ``emulate_stock_thermal.py`` executes the original bounded stock
AArch64 routine with Unicorn, intercepting only profiling and printk, for
slopes0/1/7/63 and both signs. The generated independent expected coefficients
are in ``evidence/stock-thermal-slopes.json`` and all are tested against native
decoding, including ID0 slope suppression. Disabled calibration and DEGC outside38..60 are rejected instead
of stock's default-value workaround. Measurement rails, temperatures outside
-50..150C, and incomplete transactions are invalid; no old value is reused.

Measurement and freshness contracts
----------------------------------

``pmic-thermal-adc-owned=1`` additionally transfers exclusive initialized AP
ownership of PMIC die/VCORE/VPROC ADC channels and shared CH4/DCXO mux. It
requires the existing ``adc-verified`` and PWRAP admission. The common ADC
mutex serializes native battery, NTC and thermal requests. No mux/rail setting
is written. Die sampling rejects DCXO mux bit4 in PMIC1216 and checks it again
after conversion. Another processor must not change these channels or the mux.

The exact stock table gives:

=========== ============= ============== ======================
Sensor      Request       Output         Data
=========== ============= ============== ======================
Die         110e bit4     1090           READY15, raw[11:0]
VCORE       1114 bit5     10d8           READY15, raw[11:0]
VPROC       1114 bit6     10da           READY15, raw[11:0]
=========== ============= ============== ======================

Only these measurement-request writes are made. After the request, native code
requires an observed READY low, then waits at least80us and polls READY high
with a160-iteration/200us bound. A preexisting high READY is rejected, even if
it might represent a conversion completed faster than our read. This is a
conservative freshness requirement that may need measured timing refinement
on real hardware. It does not infer freshness from a changing temperature.
Polling bounds assume MMIO transactions return; hung interconnect recovery
is not implemented. A nonzero thermal conversion result does not establish
the loader's ownership or physical sensor correctness by itself.

``cpu-thermal-observe-verified=1`` permits read-only access to thermal
controller1100b000 and the exact efuse window. The producer must establish
correct powered clocks, initialized sensor routes/ADC, calibration shadow
availability and preserved hardware protection. Native checks each bank's
enabled sensors and absence of measurement pause bits before conversion.
Bank0 channels0/1/2 map to MCU1/2/3; bank1 channels0/1 map MCU4/5 (the actual
stock table resolves an inconsistent BSP comment). Results come from
offsets90/94/98/190/194. They have no proven conversion generation counter.
Therefore CPU results are **cached observations**, and their freshness bits
remain clear regardless of numerical plausibility or repeated reads.

All publication uses a two-second observation expiry checked at sysctl read
time, so a stopped worker cannot leave a permanent valid temperature. Failed
reads immediately clear the corresponding bit. ``mt6762_thermal_observed``
contains PMIC0..2 and CPU3..7; ``mt6762_thermal_fresh`` can contain PMIC0..2
only. Invalid/stale temperature sysctls return -273000mC. The PMIC read API
also checks expiry. CPU freshness, battery thermal limits and current-policy
readiness are not implied by these properties.

Recovered stock limits and remaining policy gap
-----------------------------------------------

The exact CPU trip table at 0xffffff8009850098 contains
117000/95000/85000/65000/63000/60000/55000/50000/45000/40000mC.
BSP initializes four active trips:117C system reset,95C cpu00,85C cpu03,
65C adaptive cooling. Adaptive configuration0 targets75C with400..2000
CPU power-budget units and200..700 GPU units. These are compiled initial
policy settings, not proof of active Android thermal policy or a safe new
operating envelope; userspace can replace configuration and cooling mappings.

The actual DT ``mt6357-battery_oc_throttling`` provides ``oc-thd-h=4670``
and ``oc-thd-l=5500``. Stock enables battery-overcurrent and low-battery
throttling. The exact probe at0xffffff8008667dc4 reads these DT properties
and depends on gauge sense-resistor/car-tune data; thresholds and IRQ roles
must be interpreted together with calibrated current acquisition. They are
not a CPU per-rail current limit, and must not be used as a CPU budget or
charging-current target. No native OC/low-battery interrupt policy is attached.

The original gauge DT values R_FG_VALUE10 and CAR_TUNE_VALUE100 are scaled
by10 in the stock OC probe. MT6357 selects DEFAULT_RFG100 and
UNIT_FGCURRENT314331. Its integer threshold computation is::

  scaled = (((mA * r_fg * 1000) / DEFAULT_RFG) * 1000000 / car_tune)
  counts = ((scaled / UNIT_FGCURRENT) * 95) / 100
  register = 65535 - counts

All divisions truncate. The 95% factor is recovered stock behavior, not a
new margin selected for this port. Original boot logs independently confirm
``r_fg=100 car_tune=1000 DEFAULT_RFG=100 UNIT_FGCURRENT=314331`` and
``4670mA(0xc8de), 5500mA(0xbf11) Done``. Stock MT6357 match descriptor
at0xffffff80098090f0 maps H threshold to PMIC0xd8e and L to0xd8c, both
16-bit fields. H IRQ emits level0/recovery and enables L; L IRQ emits
level1/throttle and enables H. The PPM OC callback at0xffffff80086863fc
requests power-budget600 for level1 and releases that constraint for other
levels, subject to policy enablement and all other PPM constraints. These
records support a future readback/IRQ implementation; they do not prove
current comparator settings, IRQ delivery or calibrated current on a new boot.

CPU freshness needs a separate ownership-aware extension. BSP identifies
TEMPMONINTSTS W1C at bank+0x10, immediate-result flags16..18 and filtered
result flags19..21, plus bus-timeout15. Their asserted state is latched, not
a generation counter. Reading an already-asserted bit cannot prove another
conversion. Clearing/re-arming measurement flags would be an active ownership
operation and must preserve hot/cold/SPM protection and the prior IRQ handler.
The provided source does not demonstrate a passive generation counter.
Hardware thermal protection separately uses TEMPPROTCTL0x20000, calibrated
TEMPPROTTC and interrupt-enable31 to SPM, with watchdog direct-reset routing.
Simply enabling sensor clocks or receiving a valid-looking sample does not
establish that independent protection path. No related-chip web datasheet
was treated as proof of MT6765 register semantics.

Exact-stock freshness audit
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``evidence/cpu-freshness-admission.json`` and the bounded
``evidence/thermal-status-disassembly.txt`` corroborate the status path in the
actual dumped Image. The handler reads bank+0x10 and writes the same complete
status word back, then executes ``dsb sy``. A concurrent stock-style IRQ owner
therefore also clears measurement flags; a new observer needs coordinated
acknowledgement ownership while preserving hot/cold/SPM handling.

The stock initializer writes filter configuration0x492 (two-of-four samples),
and its temperature reader uses filtered ``TEMPMSR`` at0x90/94/98. Functions
named ``get_immediate_*`` expose cached converted readings; they do not establish
an immediate-register path. Immediate completion bits16..18 cannot certify
these filtered readings. Candidate filtered completion masks are0x380000 for
bank0's three sensors and0x180000 for bank1's two sensors. These masks are
protocol design evidence, not permission to acknowledge them on hardware.

A future admitted observer would write only its selected W1C bits, require an
observed clear followed by assertion, and read the corresponding filtered
result with ordering and a validated timeout. It must never acknowledge a
full status snapshot or modify IRQ enables, protection, pause, clocks or
sensor routes for this purpose. Exact stock does not independently exercise
completion-bit semantics, prove assertion with measurement IRQ enable clear,
or establish completion/data visibility ordering. Those facts and physical
ownership remain unverified. CPU freshness and DVFS control stay disabled.

A safe performance governor still requires fresh CPU temperatures (or a
verified independent protection/observer contract), calibrated shared-rail
current/budget, active cooling limits, coordinated SSPM/PPM/CCI policy and
an independently reliable failure action. ``dvfs_control_ready`` remains0.

Validation
----------

``test.sh`` builds the same native protocol header with warnings as errors.
Known historical calibration vectors reproduce logged coefficients and
temperature-at-calibration points; CPU conversion is monotone over valid raw
inputs. Tests reject missing/invalid calibration, rails, wrong mux, bus errors,
stuck READY, timeout and stale publication. All three PMIC register paths are
checked and failed outputs remain unchanged. Physical ADC transition timing,
temperature accuracy and thermal protection remain untested.

Actual eight-core XNU build12 laboratory runs reject thermal timeout, stale
READY, calibration-disabled, bad-DEGC and rail faults: no valid/fresh bits or
successful samples are published. Calibration faults issue zero measurement
requests. Wrong CH4 mux issues zero die requests, invalidates die only, and
permits independent buck measurements; occasional conservative READY timing
rejections can invalidate individual buck samples. All six runs retain the
PID1 input queue, bring up eight CPUs and have no observed panic. Exact
kernel/model hashes and observations are in
``evidence/native-thermal-build12-faults.json``. These fixture results do not
validate physical temperatures, charging or a thermal control policy.
