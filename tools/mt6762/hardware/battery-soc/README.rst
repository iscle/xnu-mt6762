Conditional approximate SOC model
================================

This standalone, default-off C core is for an explicitly approximate UI estimate.
It is not integrated into XNU, the loader, IOKit or any charger control. No phone
measurement was taken by this work. Do not use its outputs as charging, shutdown,
thermal, battery protection, learned capacity, or exact Android-daemon policy.

The output is an interval in basis points (10000=100%). There is deliberately no
single preferred percentage, measured temperature, remaining time or learned
capacity. Quality flags identify the estimate, unknown temperature, conditional
resistance model, nonmonotonic vendor data and2200mAh endpoint normalization.
The interval is conditional model uncertainty, NOT a physical confidence bound.
Unknown voltage/gauge calibration, relaxation, hysteresis, aging, physical cell
identity/capacity and resistance error can put the true SOC outside it.

Profile admission
-----------------

bs_profile_init requires the actual six big-endian888-byte profile payloads;
it computes SHA256 itself and matches the exact shipped hashes. No caller
"validated" boolean bypasses this. It additionally requires declared row counts
100, columns3, temperatures50/25/10/0/-6/-10, and raw DT R_FG_VALUE10,
CAR_TUNE_VALUE100, FG_METER_RESISTANCE75. Reject absent/changed/duplicate metadata
in the future FDT integration before calling this API. The core consumes byte
spans and values, not a whole FDT; validating the surrounding live board/gauge
node and its ancestors remains that caller's responsibility.

The actual profile contains74 rows; original ARM64 code repeats its last row
through100. Repeated endpoints do not add curve geometry, so this core stores
only the74 source rows. T0..2 share SHA256
 d4d40034e86047a42318bcdceab41e256e903da4f19e7947ecf8bec0837fa5cf
and T3..5 share
 b878eecf8515ac02a25b526ccdcf1daf926d9547e8fff875c358e082d02ca58d.
No proprietary profile payload is embedded in these sources. Validated decoded
profile objects must remain immutable and come only from bs_profile_init. Their
marker checks programming misuse, not adversarial in-process memory mutation.

All voltage/resistance columns are identical across the six shipped tables;
early discharged-charge coordinates differ slightly. A voltage reversal occurs
at row12 and a charge backstep at row64. No rows are silently sorted, removed or
repaired. Pure bs_ocv_interval checks all overlapping segments and keeps every
charge intersection from all six temperature profiles, with outward integer
rounding. It therefore represents local multi-valued ambiguity rather than
choosing the stock algorithm's first crossing. Because voltage coordinates match
across tables, intermediate temperature interpolation is contained in this
six-table envelope. No25C physical reading is assumed.

Stock provenance and intentional differences
-------------------------------------------

Original Image SHA256:
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
Private source-bound evidence is retained in
hardware/hakios-migration-20261026/battery58/soc-profile/:
FINDINGS.rst, stock-soc-functions.json/stock-soc.asm, original-replay.json,
dt-profiles.json and source-hashes.json. The evidence includes execution of the
original ARM64 header/DT parser, temperature construction and OCV interpolation
with explicit host mocks and synthetic inputs; it is not a physical battery test.

Exact entry points include fg_custom_init_from_dts ffffff8008a7caec,
its inlined triple parser a7de04..a7df18, fgr_construct_battery_profile
ffffff8008a81358, fg_construct_battery_profile_by_qmax ffffff8008a819ac,
fg_construct_battery_profile_by_vboot ffffff8008a81ab4, fgr_construct_vboot
ffffff8008a81e18, OCV_to_SOC_c ffffff8008a82cdc. Relevant BSP cross-checks are
kernel-4.14/drivers/power/supply/mediatek/battery/mtk_battery_core.c850..910,
1255..1412 andmtk_battery_recovery.c1409..1709,1842..2008.

The discharged-charge endpoint22000 is0.1mAh, hence the explicit project model
capacity2200000 microamp-hours. It is neither measured capacity nor a claim that
the stock algorithm always selects this denominator. Stock QMAX_SEL1 derives
normalization from load/cutoff/PTIM resistance; compiled default Qmax arrays
also differ. That policy is deliberately not reconstructed here. Original
first-crossing arithmetic under an explicit3350mV cutoff produces3715mV23.62%
and3705mV25.83%, demonstrating why voltage must not continually reseed the UI.

Initial estimate
----------------

bs_begin(state,1) explicitly opts into this conditional model. A zero/default
state has no estimate. It takes two valid, forward, generation-continuous
observations before producing the initial seed; the first only establishes a
baseline. Both observations must carry fresh VBAT, current and signed CAR from
one coherent observer snapshot. No absent measurement is substituted.

For the second observation, the conditional OCV interval is:

  VBAT - current_uA * R_0.1mOhm / 10000

Positive current means charging, so its terminal voltage is corrected downward;
negative current corrects upward. R uses the full actual table range740..990 plus
the stock series terms R_FG100 and FG_METER_RESISTANCE75, i.e.91.5..116.5mOhm.
This envelope avoids guessing a temperature or a particular resistance row.
Outward rounding and an extra±1000uV cover integer ADC millivolt flooring only.
They do not cover physical calibration error. Series compensation is justified
as a stock software model, not verified electrical accuracy or a rested cell.
There is no claim that two observations constitute an OCV rest period.

bs_ocv_interval is also independently callable with an explicitly conditional
OCV interval, without opting into the resistance assumption. Its arithmetic-only
result has valid=0 and no freshness timestamp. A later integration may prefer
this lower-level API if physical electrical assumptions cannot be admitted.

Updates and explicit bounds
---------------------------

After seeding, voltage is never used to reseed or adjust SOC. The core adds the
observed signed CAR difference relative to the seed, using2200000uAh as the
model denominator. It retains the inherited counter's arbitrary origin; +8Ah
and-8Ah origins with equal deltas give the same estimate. Rounding is applied
from the baseline on every update, avoiding cumulative per-poll truncation.
A±200uAh arithmetic allowance covers quantized endpoint differences in the
reported interval. This is not a bound on physical coulomb-counter accuracy.
The OCV fields retain their separate ocv_acquired_us seed timestamp, even while
current output acquisition/expiry fields advance.

The following are explicit project admission rules, not claims about hardware
maximums or stock UI policy:

* All times are monotonic microseconds. Caller converts native absolute ticks
  with checked arithmetic before calling. Input lease starts BEFORE all I/O:
  acquired<=now<expires, expires>acquired, expires-acquired<=2000000us.
* Acquisitions strictly increase; every update/read now must not move backward.
  Consecutive acquisition gaps are at most5000000us. Caller must call bs_read
  when acquisition stops so the output expires at its original deadline.
* Sequence numbers strictly increase; nonzero generation identifies the same
  admitted continuous gauge/configuration epoch. Changing it invalidates state.
* The33-bit NTER must advance by a modular delta in[1,2^32). Natural forward
  wrap is allowed, following the existing native observer. No assumed2Hz-to-wall
  relation is imposed:2Hz is only the QEMU fixture rate, not recovered physical
  timing. The native latch/configuration/freshness checks remain prerequisites.
* Current is signed microamps, quantized100uA by the exact decoder, with allowed
  magnitude at most2000000uA. Voltage is2500000..5000000uV, quantized1000uV by
  the exact stock processed conversion. The conditional OCV interval must also
  stay within2500000..5000000uV or admission fails.
* CAR is signed microamp-hours, quantized100uAh; magnitude above20000000uAh is
  rejected as out of the supported decoded-counter envelope. It is not remaining
  charge. Success requires valid==7 (VBAT/current/CAR), not native BAT_* flags.
* Each CAR delta must satisfy abs(delta)<=ceil(2000000*gap_us/3600000000)+200
  microamp-hours. This accommodates quantization but bounds implausible jumps.
  It does not assume endpoint currents bound all intervening transient loads.
* When both endpoint currents have the same nonzero sign, a CAR delta of the
  opposite sign beyond200uAh is rejected. A real intervening direction reversal
  could produce a conservative false rejection; endpoint current alone cannot
  prove the complete waveform. Different endpoint signs are allowed.
* The integrated model interval must remain wholly within0..10000 basis points.
  Crossing a boundary invalidates it instead of silently pinning0/100. This
  deliberately means near-full/empty estimates may require future qualified
  boundary policy; it does not signal hardware full/empty or control charging.

A stale, partial, reversed-time, discontinuous, implausible or out-of-model
observation clears the output and latches failure. It never silently reseeds.
Restart requires an explicit new bs_begin after the integration has re-established
its measurement/continuity prerequisites. The core cannot detect every small
CAR-only reset that leaves NTER/configuration apparently continuous; an unknown
reset can resemble a small valid delta. Therefore independent gauge ownership,
no unaccounted reset writers, and epoch changes on known resets are mandatory
integration assumptions. Without those, use arithmetic-only lookup and do not
publish a tracked estimate.

No broadening of permission follows from profile identity or sample valid bits.
The caller must serialize access; profile/state/sample/output spans must not
alias. It must keep the admitted profile immutable, pass the actual same-boot
profile/coefficients and fresh snapshot, remove expired UI properties, and
avoid translating an interval midpoint into unwarranted precision. This package
adds no callbacks, driver invocation, hardware action or publication code.

Tests
-----

  BS_PROFILE_DTB=/private/capture44/runtime.dtb python3 test_battery_soc.py -v

The suite compiles actual C with optimization, -Wall -Wextra -Werror and
-ffreestanding. It tests SHA256 against hashlib across padding boundaries;
corrupt/truncated/mismatched profiles and metadata; exact rational segment
intersections; nonmonotonic ambiguity; signed IR correction; baseline-relative
CAR integration for1000 updates while voltage alternates; quantization/jump
boundaries; sign/generation/sequence/NTER/time guards; expiry and model bounds.
All measurement streams in tests are explicitly synthetic. The optional real
DTB supplies immutable profile bytes only, not live measurements. Without it,
three artifact-authentication/default-off tests run and the real-profile class
is explicitly skipped. No raw private profile bytes are bundled with this code.
