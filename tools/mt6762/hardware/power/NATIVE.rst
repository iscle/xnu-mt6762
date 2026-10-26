Native XNU integration
======================

``bsd/dev/mt6762_power.c`` observes power and quiesces an owned charger. It consumes the common version-1
``/chosen/mt6762-handoff`` contract and starts no hardware path without
``native-io=1`` accepted by ``mt6762_platform_init``. This is source under
validation, not a working physical-device charging implementation. Physical
capture20 confirms profile2 read-only PMIC identification and rail reads.
Capture24 additionally confirms native Power/Volume Up/Volume Down press and
release events. ADC, gauge and charging remain unaccepted. The ordinary
QEMU boot has none of these native flags.

Ownership and readiness
-----------------------

The optional ``charger-readonly-probe=1`` works inside the inherited PWRAP
diagnostic path, before its button worker starts. It additionally requires
I2C5 to have completed its own handoff/setup admission; the flag never
initializes that bus. It reads fixed PSC registers3,1,0, requires ID0xf0,
and retains two complete observations in ``MT6762_PSC_PROBE`` lines. Failed
reads stop this probe and do not publish partial values or charger readiness.
The existing key worker can still start. There are no charger configuration
writes, battery-policy operations or charge-enable grant on this path.

These sequential observations are not atomic and do not establish exclusive
charger control or protection. Manufacturer Rev06.5 says I2C activity can
refresh the OTG watchdog, so register reads are not electrically passive.
Host tests cover every control/status byte pair,255 wrong identities, each
read failure, missing arguments and operation without a write callback.
The installed Image33 predates this addition; its pending I2C5 capture is
still needed before a physical bus profile can enable the probe.

* ``pwrap-verified=1`` means the loader has checked the inherited PMIC wrapper
  and transferred AP WACS2 use with previous AP users quiesced. The physical
  profile2 uses initialization bit22; legacy bit21 is allowed only in the
  explicit laboratory profile. The driver separately checks readiness and reads PMIC
  hardware ID at 0x0008, requiring the MT6357 family byte 0x57. A timeout or
  lost initialization latches a fault. It does not reset or clear an unknown
  owner's transaction. SSPM/modem channels are not claimed by this contract.
* ``adc-verified=1`` additionally grants exclusive use of initialized ADC
  channels 1 (ISENSE, the stock DT battery-voltage input) and 3 (BAT_TEMP),
  with their stock averaging/reference configuration. This is a loader
  prerequisite, not something a flag initializes. Hardware readiness is
  observed per conversion through bit 15 of the output, and timeout/rail
  readings are rejected. Configuration and electrical calibration still need
  physical readback validation. The only worker PMIC writes are request bits
  1 or 3 to AUXADC_RQST0 (0x110e). No VBIF request, BATON detection changes,
  regulator writes, or charge-enable writes occur. Owned charger quiescence is described below.
* ``keypad-verified=1`` grants the already clocked and configured keypad
  register block at 0x10010000. The driver checks KP_EN bit 0 on each sample.
  It observes matrix index 0 for volume-down and index 1 for volume-up, as
  confirmed by physical stock input capture. PMIC TOPSTATUS bit 1 supplies
  power. The advertised PMIC home/volume-up mapping is not used.
  Boot-held keys are ignored until released; transitions require two samples,
  and failed reads release any previously emitted key.
  The optional physical ``keys-inherited-probe=1`` path additionally checks
  the captured GPIO92/93/94 mux, keypad enable/debounce/selection and masked,
  inactive INTID212 twice before entry and on each poll. A changed keypad
  profile stops key reporting and releases held events. It keeps PMIC access
  read-only and starts only the button worker, without ADC/gauge/charger
  operations or battery publication. ``--native-buttons-probe`` requests this
  path in the physical builder; both grants begin zero. Kernel43 compiles
  this path, with host admission tests and the existing emulated input
  regression passing. Capture24/kernel48 records two press/release pairs for
  each of the three physical buttons; see ../storage/capture24-native-evidence.json.
  Physical iOS event delivery remains untested. Captured values are
  in physical-keys-profile.json; emulator results are in native-build43-evidence.json.
* ``charger-verified=1`` plus an independently ready I2C5 bus permits access
  to PSC5425E at 0x6a. A real handoff additionally requires
  ``charger-control-owned=1``. The loader must already disable charging before
  jumping and transfer exclusive control, with an independently verified
  fallback if the bus fails. XNU checks identity 0xf0, reads control register
  1, sets CE-disable bit 2 if needed while preserving every other bit, and
  verifies exact readback. The worker repeats this each poll. Boost mode is
  rejected because OTG ownership/routing is not established. No charge-enable
  operation exists. Failed bus/readback means safety UNKNOWN, not disabled.
* ``lab-fixture=1`` permits an explicitly synthetic observation-only test
  without control ownership. Such a test never yields control-safe readiness.
  The preferred fixture also sets ``charger-control-owned`` and exercises the
  same disable/write/readback path. Laboratory results do not confer physical
  readiness. The separate ``mt6762_charger_control_safe()`` reports only the
  last checked disable readback, not complete battery protection or port
  readiness. Status 3 is reserved and omitted; an apparent charging state
  while CE-disable is confirmed is treated as inconsistent, not fabricated
  as not charging.

Polling uses a kernel worker (nominal 16 ms for buttons, approximately one
second for power), not IRQ handlers. Exclusive AP ownership and initialized
clocks/pins are bootloader handoff requirements. Polling does not preserve
Android's interrupt wakeup, suspend, long-press shutdown, or thermal policy.
The 16 ms period may be delayed by bounded bus transactions.

Truthful battery properties
---------------------------

The internal ``mt6762_battery_sample`` has an explicit validity mask and a
separate call path to IOKit. The existing redwood userspace/battery structure
has not changed. Every sample replaces validity; missing IOKit properties are
removed from both the internal power-source dictionary and IORegistry.

Known observations can include battery detection (only while BATON detection
is enabled), PMIC external power, nominal ADC voltage, and PSC state. Current,
SOC, and calibrated temperature are not available from the basic observer.
The separately gated fuel gauge can supply signed current (see ``GAUGE.rst``). A nominal NTC estimate is
exposed only in a diagnostic sysctl, never as battery temperature or as
permission to charge. The stock 25 C constant is not reused. Native sysctl unknown current uses INT_MIN; validity must also be checked via
``kern.redwood.mt6762_power_valid``. Unknown SOC, voltage and presence use -1,
and unknown temperature uses -273. The ordinary Redwood legacy path is unchanged.

A real handoff must leave charging disabled or retain an independently
verified protecting controller. Inheriting an enabled charger while Android
thermal logic is gone does not satisfy this prerequisite.

No maximum capacity, adapter budget, unknown current, temperature, or charging
capability is invented. Because powerd normally requires CurrentCapacity and
MaxCapacity, a missing iOS percentage is expected until a real calibrated
gauge implementation exists. This implementation does not satisfy autonomous
charging, thermal protection, battery percentage, suspend, or native DVFS.
The actual cell limits, board sense resistance, NTC compensation, Coulomb
calibration, adapter budget, and handoff readback remain required work. Chip
register/timer semantics are now grounded in the linked manufacturer audit.

Host and emulator validation
----------------------------

``./test.sh`` compiles the exact native protocol header with injected register
callbacks and tests WACS2 command/valid-clear order, bounded polling,
initialization loss, no result publication on errors, ADC conversion/scaling,
rail rejection, and button arming/debounce/failure release. These are protocol
fixtures, not measurements from a phone. Charger tests exercise the actual native ownership/disable/readback path,
identity failure, read/write faults, register preservation, and nominal
manufacturer decoders. ADC request/sample counters and observed millivolt
min/max expose whether any real conversion occurred; zero requests do not
validate a temperature. The original recovered-protocol and nominal-thermistor
tests also run. No sanitizer claim is made.

An opt-in QEMU I2C fixture can exercise the native charger transaction path
with ``charger-verified``, ``charger-control-owned``, and an initialized lab
I2C5 handoff. Its deterministic
identity/state values are synthetic; they cannot establish physical charger,
PMIC, ADC or charging functionality. Review the parent integration logs for
the exact kernel build and emulator result.

Acquisition age and publication expiry
-------------------------------------

Native reports carry internal ``acquired_abs`` and ``expires_abs`` timestamps,
not an Apple ABI change. Acquisition is stamped before PMIC/ADC/charger reads.
The deadline is no later than acquisition plus two seconds and is shortened
to an included gauge reading's own expiry. Slow reads and delayed delivery
cannot extend source lifetime. Missing, future, overlong and already expired
timestamps are rejected. Acquisition time orders reports independently of
expiry: a newer report may legitimately have an earlier source deadline.

``report_expiry.h`` is shared by the BSD snapshot and IOKit consumer. The BSD
mutex is released before entering IOKit. Native ``RedwoodBattery`` uses its own
IOWorkLoop and IOTimerEventSource; report publication, timer expiry, stop and
cleanup share that gate. An old queued callback examines the current deadline
and cannot erase a newer fresh observation. At expiry the service publishes
``MT6762ValidFields=0`` and ``MT6762ReportExpired=true`` and removes measured
properties from both the power-source dictionary and IORegistry. Unknown is
represented by absent properties, not zero voltage/current or false presence.
Fresh delivery restores only valid fields and clears the expired flag. A fresh
explicit invalid report clears fields immediately without claiming an age
timeout. Stop cancels the timer and is terminal; free drains the gate and
removes/releases the timer. Ordinary Redwood reports create no expiry timer.

The timer deadline is absolute and armed before publication; actual callback
delivery remains subject to kernel scheduling. This is not a hard realtime
guarantee during a stalled kernel. BSD scalar getters independently check age
at read time. Raw ADC diagnostics describe continuing acquisition and must not
be interpreted as the age of the separately published battery snapshot.

Original iOS16.5 powerd matches IOPMPowerSource, subscribes to the battery-status
message and rereads properties. Its capacity checks reject missing
CurrentCapacity/MaxCapacity. ``evidence/powerd-publication-contract.json`` records
bounded addresses and file identity. IOPMPowerSource::updateStatus copies
present keys and notifies clients but does not remove missing keys; explicit
removal is therefore required. No percentage is fabricated to satisfy powerd.

``./test.sh`` includes source-age, expired-arrival, shortened-deadline, queued
old-timer, duplicate/older-report, stop and overflow-boundary vectors. Runtime
validation uses the original IOKit framework through the read-only
``battery_probe 100 1000`` helper. Each iteration takes one registry dictionary
snapshot and reports named fields, expiry state, and read-only BSD counters.
A snapshot can still intersect a multi-property update; the test requires
repeated complete expired observations and later recovery.

The optional ``battery-report-gap-start-ms``/``battery-report-gap-ms`` handoff
properties require ``lab-fixture=1`` and are disabled by default. They suppress
report delivery to BSD and IOKit only; acquisition and key polling continue.
The planned explicit 60-second start/8-second gap checks that the timer and
getters invalidate a stopped publisher without relying on new invalid reports.
This synthetic test does not model a physical PMIC or establish charging safety.
