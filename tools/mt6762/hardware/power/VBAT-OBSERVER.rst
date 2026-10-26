Fresh inherited channel 1 battery voltage
========================================

The optional observer adds a single narrowly permitted ADC request to the
inherited battery observer. It publishes voltage only, alongside whatever
presence, external-power, charger-state and coherent gauge fields are valid.
It does not enable charging or publish a percentage, temperature or remaining
capacity. Existing broad ADC ownership and public PWRAP writes remain disabled.

Exact source and captured configuration
---------------------------------------

``audit_vbat_profile.py`` retains identities, fields and source locations in
``evidence/vbat-profile-source.json``. The original stock Image SHA-256 is
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
Its channel 1 descriptor at 0xffffff8009893308 has 15-bit resolution and null
conversion/calibration callbacks. The original register table entry at
0xffffff8009105f04 gives request 0x110e, shift 1 and result 0x108a. The actual
capture44 DT maps pmic_battery_voltage to that provider/channel, with
resistance-ratio 3:1 and avg-num 128.

Original get_auxadc_out at 0xffffff8008b6aab8 writes 0x110e=2, waits 1280–1290 us,
then polls the result's READY bit. mt635x_auxadc_read_raw at 0xffffff8008b6b8fc
scales the raw count by 3*1800 then shifts 15, producing integer millivolts.
The probe attaches a BAT_TEMP calibration callback and DCXO/BIF conversion
callbacks; none is attached to ISENSE/channel 1. The native fresh initialization
reuses this original conversion with matching hardware trim/configuration;
it does not reconstruct mutable Android callback state or apply a second
invented factory correction. ``emulate_stock_vbat.py`` runs both original ARM64
functions with mocked transport/time/locks and preserves nine independent
vectors in ``evidence/stock-vbat-vectors.json``. Its execution is offline.

Both complete capture44 passive ADC passes match the fixed 19-word profile:
HWCID/SWCID 5730 and the 17 ordinary configuration/trim words, including digital
gain/offset shadows 10de/10e0, listed in mt6762_vbat_profile.h. The profile preserves
actual captured values, rather than assuming default factory trim. No claim
of independently measured absolute voltage accuracy follows from this match.

The actual AUXADC clock/reset controls are separate from the gauge clock word.
Five additional ordinary readable words are required. They were not in the
capture44 passive record and therefore are collected by the new producer:

* 0x0f8c HK_TOP_CLK_CON0: low 10 bits must equal 0xaa. The dumped original
  preloader contains the tuple {0xf8c,0xaa,0x3ff,0} at file offset 0x37fd8,
  agreeing with the supplied MT6765 preloader initial-setting table.
* 0x0f8e HK_TOP_CLK_CON1: bits 0..2 clear (normal divider, no test clock,
  interpolation clock not disabled). The original table sets divider bit 0
  clear; the other two requirements come from their defined control fields.
* 0x0f90 HK_TOP_RST_CON0: low 8 bits clear; no HK/ADC bank/reset asserted.
* 0x113e AUXADC_CON13: mask 0x3449 clear; no RNG/test mode, software start/mux/
  buffer override or alternate output. Inactive value fields are retained
  and compared across the transaction without inventing their defaults.
* 0x114c AUXADC_CON20: mask 0x500 clear; unqualified DATA_REUSE_EN bit 8 and
  channel 1 DATA_REUSE_EN bit 10 must both be disabled. See the unresolved
  hardware coupling below.

The entire observed 16-bit word, including bits outside a readiness mask, is
passed through the handoff and rechecked before and after each conversion.
A matching source table is evidence about intended initialization, not proof
that a particular physical boot reached it. Runtime reads remain mandatory.

Handoff and implementation
---------------------------

``mt6762_vbat_profile_from_fdt`` validates a bounded caller-owned FDT, including
exact root/PWRAP/PMIC/provider paths, compatible lists and statuses; named
consumer routing; unique provider phandle; a unique channel 1 description;
and explicit ratio 3:1/averaging 128. Missing, malformed, duplicated, disabled or
ambiguous descriptions reject. Provider phandles may differ from captured 39;
the query resolves them, rather than assuming that numerical identifier.
There is no default fallback and no change to the existing FDT structure ABI.

The explicit producer flag is ``--native-vbat-observer``. The consumer requires
battery-inherited-observer and the validated inherited read-only wrapper, plus:

* vbat-inherited-observer=1 and vbat-adc-profile-version=1.
* vbat-adc-clock0, vbat-adc-clock1, vbat-adc-reset, vbat-adc-test and
  vbat-adc-reuse: full live words encoded as LE32; values above 65535 reject.

The producer owns its separate two-pass 48-read acquisition and diagnostics;
a failed profile cannot issue a grant. The kernel checks the exact 24-word
profile before and after each acquisition and serializes ADC use. Only the
currently admitted local context, in its conversion phase and inside its
original two-second battery lease, can issue one attempted write 0x110e=2.
No SET/CLR alias, second request, other channel, reset, TDET, gain/offset,
clock or charger write can use this capability. The shared public PWRAP write
API remains refused, including from inside the modeled transaction callback.

The unchanged fresh ADC protocol requires observing READY low after the request
and then READY high. It rejects a missed generation, timeout, rails or partial
transport. The native readiness requirement is stricter than the original
stock routine, which simply delays and accepts READY high. A successful sample
uses the stock integer-mV rounding, multiplied by 1000 for voltage_uv. It shares
the original acquisition deadline and adds MT6762_BAT_VOLTAGE to the existing
battery ABI; there is no lifetime renewal at completion. Without a valid
voltage, that validity bit stays absent. Failed ADC protocol/configuration is
terminal for voltage during the boot; independently valid gauge/charger
observations may continue. PWRAP transport failure stops the whole observer.
There are no retry, recovery or cleanup writes.

The stable compiled-support marker is::

  MT6762_VBAT_OBSERVER_READY channel=1 max_requests_per_sample=1

The battery-observer lock declaration now lives with the other power.c locks,
not in the included C file. This avoids XNU's line-number-derived STARTUP_ARG
symbol collision with the included gauge-probe declaration. The standalone
host fixture supplies its own lock; no kernel header or IIG input changed.

Data-reuse limitation and next physical evidence
------------------------------------------------

The dumped preloader also contains {0x114c,0x100,0x103,0}: it enables the
unqualified bit 8 and selects 0. The supplied field catalog exposes separate
unqualified/CH0/CH1/DCXO selectors and enable bits 8/9/10/11. That grouping alone
does not establish their internal Boolean coupling. In particular, the source
review cannot prove that channel 1 bit 10 clear makes bit 8 harmless for channel 1.
The original ADC request/read path does not read or change 0x114c. Its normal
operation under inherited configuration does not prove the native freshness
predicate is sufficient when data reuse is enabled.

Consequently this version may refuse voltage sampling on the actual boot if
bit 8 remains set. It retains the whole live word in producer diagnostics while
keeping the observer grant clear. This is a documented readiness boundary,
not a claim that the displayed voltage or percentage is fixed. No guessed
reuse-disable write or mask relaxation was added. A later decision needs the
actual live word plus hardware semantics or a separately justified bounded
reuse-control experiment. Current-sample validity, a prior READY value and
stock's successful reads cannot resolve that coupling by themselves.

This limitation concerns fresh voltage admission. The inherited charger state
and gauge-current observer from kernel58 remain independent, and no charging
control is authorized by this path. The separately developed SOC model is not
integrated here. Raw voltage while charging is not a rested OCV measurement.

Verification
------------

The host suite compiles the actual consumer and private/public WACS paths with
unchanged ADC protocol code. It covers 215 transport failures, 48 before/after
shadow changes, 54 expiry positions, expiry waiting for the ADC lock, all
handoff fields, generation/timeout/rail failures, publication replacement,
combined gauge+voltage samples, callback context/address/phase/budget misuse,
and the nine original ARM64 conversion vectors. The original inherited battery
suite still passes its 272/16/70 cases. Seven profile-test groups cover actual
capture44 and dumpedDT, phandle variation/collisions, all required-field
omissions/duplicates, disabled ancestors, malformed routing, every accessible
truncation and 1000 deterministic mutations. These are host tests; no physical
new-voltage observation is claimed. Run ``sh tools/mt6762/hardware/power/test.sh``.
