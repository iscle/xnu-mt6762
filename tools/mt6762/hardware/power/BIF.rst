Fresh battery ADC and gated BIF diagnostics
==========================================

This increment supplies fresh conversion detection and a testable exact-restore
TDET protocol. Native use exposes raw NTC/BIF pairs only. It neither publishes
calibrated battery temperature nor enables charging. No physical execution has
been performed.

Protocol and test boundary
--------------------------

bsd/dev/mt6762_bif_protocol.h implements post-request READY-low then READY-high
observation for MT6357 hardware channels 1, 3 and 11. The outputs are respectively
0x108a/15 bits, 0x108e/12 bits and 0x109e/12 bits. All use the request register
0x110e. The stock averages imply initial waits of 1280/80/80 microseconds;
there are at most 160 additional polls with 200-microsecond waits. Bus operations
have their own finite wrapper deadlines. Missed low transitions, timeouts,
reserved data and ADC rails fail without modifying the output. The native
battery/NTC ADC wrapper now uses this helper instead of accepting cached READY.
A fast conversion that completed before software observed low is rejected;
it is not silently treated as fresh.

The standalone BIF pair protocol first validates the handoff TDET word and
samples NTC. It rechecks TDET, temporarily clears bit 1 only if necessary,
samples BIF, and restores the exact original word only when the current word
matches the transaction's expected phase. An unexpected word is ownership loss,
not permission to overwrite a concurrent writer. Original-clear TDET receives
no write and must still match after the conversion. A failed transfer may have
reached hardware; restoration is checked, never assumed. A restoration that
cannot be verified sets restoration_unknown and stops further transactions.
Every low-level pair failure latches a fault and leaves both outputs unchanged.
Build18 adds narrowly scoped next-period retry admission for error -5 only: the
original TDET bit must already be clear, no restoration may be uncertain, all
configuration words must pass a new post-capture check, and another exact TDET
readback must succeed. The rejected pair remains invalid. I/O, timeout,
ownership, configuration and restoration failures remain sticky.

Run ``sh tools/mt6762/hardware/power/test_bif.sh``. Tests inject persistent I/O
failure at every successful-path operation, including a write that reached the
PMIC before the wrapper reported failure. They also exercise initial clear/set
TDET, silent dropped clear/restore writes, stale READY, timeout, rail/reserved
data, and concurrent change of both the owned bit and unrelated control bits.
No test invokes a physical device. The general power test suite also checks the
changed native battery/NTC wrapper's freshness behavior.

Native admission deliberately excludes changing TDET
----------------------------------------------------

There is no implemented independent fallback that restores PMIC TDET after
PWRAP becomes unusable. Therefore native admission rejects a handoff whose
bif-tdet value has bit 1 set. In addition, the native BIF callback refuses all
writes except NTC/BIF request bits at 0x110e. Even an erroneous protocol branch
cannot write 0x1236 through this callback. The broader exact-restore protocol
is host-tested infrastructure for a future verified fallback, not current
permission to change physical TDET.

Already-clear TDET diagnostics require the common native platform/PWRAP/ADC
contract, bif-adc-owned=1, baton-tdet-owned=1 and bif-trim-verified=1. They also
require bif-tdet plus all of these actual handoff readbacks:

=======================  =======  ===========================================
Property                 PMIC     Meaning from supplied MT6357 register header
=======================  =======  ===========================================
bif-sw-gain-trim          0x10de   SW gain trim shadow
bif-sw-offset-trim        0x10e0   SW offset trim shadow
bif-adc-con0              0x1120   Power/clock selection
bif-adc-con1              0x1126   Shared sample/average selection
bif-adc-con2              0x1128   Average source selection
bif-adc-con5              0x112e   Sample-count source selection
bif-adc-con7              0x1132   Channel 3 sample count
bif-adc-con9              0x1136   Dedicated channel averages
bif-adc-con11             0x113a   Channel 0–7 trim selectors
bif-adc-con12             0x113c   Channel 8–11 trim/compensation selectors
=======================  =======  ===========================================

All ten words and PMIC ID are checked before and after each pair under the same
ADC mutex used by native voltage/NTC and PMIC thermal sampling. TDET is checked
inside the pair protocol. Flags do not establish real ownership or calibration:
a physical handoff producer must establish them before supplying these values.
No physical producer or defaults have been added. Matching captured words shows
configuration continuity, not independently calibrated absolute temperature.

kern.redwood.mt6762_bif_raw and mt6762_bif_ntc_raw return raw counts or -1 when
invalid. mt6762_bif_pair_fresh is true only for a completed pair younger than
two seconds from the start of paired sampling; slow transactions cannot extend
the first sample's age. The getter reads time after acquiring the ADC mutex. Companion
bif_samples/errors/fault nodes explain completion and sticky rejection. Build18
also exposes bif_generation_rejections and bif_last_error, distinguishing a
known-state missed-generation retry from uncertain hardware state. The
existing nominal NTC estimate remains explicitly uncalibrated. BAT_TEMP stays
absent from native battery validity and Apple IOKit publication.

Why charger CE-disable is not yet a TDET restoration fallback
-----------------------------------------------------------

The independent I2C5 PSC5425E path provides a concrete CE-disable/readback and
is useful as a charging precondition. It does not restore TDET. More seriously,
its prior CE-disable cannot be assumed to survive charger input power-on reset.
The manufacturer's `PSC5425E Rev06.5 datasheet
<https://www.prisemi.com/pdf/1ldccdxp/PSC5425E.pdf>`_, page 21, describes startup
charging with defaults after VBUS POR; page 26 specifies CONTROL1 default 0x70,
whose CE bit is clear. The independent DISABLE pin overrides register charging
control (page 3), but this board's wiring and ownership of that pin have not
been established. The stock charger DT names GPIO42 only as rt,intr_gpio;
psc5425e_driver_probe has no GPIO/pinctrl calls. This does not prove absence of
physical wiring. GPIO42 has not been repurposed as a guessed disable signal.
See evidence/bif-fallback-audit.json for the bounded probe call inventory.

The `MediaTek MT6357 product brief, version 1.0
<https://www.mouser.com/catalog/specsheets/MediaTek_MTK_MT6357_Product_Brief_v1_0.pdf>`_,
page 7, identifies BATON as the battery and temperature sensing pin, but provides
no TDET circuit or lost-restoration guarantee. The supplied BSP register header
separately describes BATON_UNDET and BATON_HT status, enables and interrupts.
The exact stock BIF callback only proves that software clears TDET before
conversion and sets it afterward. It does not prove that leaving TDET clear
preserves hardware hot protection, has no other electrical effect, or is safe
across battery removal/charger reset. Those are unresolved hardware questions.
Consequently CE readback alone has not relaxed the native no-TDET-write rule.

Synthetic QEMU fixture
----------------------

The separately opt-in lab-bif fixture uses explicitly synthetic trim/config
words, TDET=4 and BIF raw=4089. It models request/ready timing, rejects all TDET
and calibration writes, and counts attempts. Faults cover initial TDET set,
configuration mismatch, timeout, cached READY, rail and TDET change during a
conversion. A separate adc-stale fault exercises the newly strict baseline
voltage/NTC consumer. These are protocol tests, not an electrical model or
physical calibration. The QTest verifies these branches and default absence; baseline power, gauge
and PMIC thermal fixture regressions also pass. Native build17 at default
80-microsecond timing conservatively rejected three BIF positive attempts
(two eight-CPU runs and one single-CPU run): one missed transition permanently
invalidated that diagnostic under build17. Those failures are retained.

An explicitly configured lab-adc-delay-us=2000 fixture delays only NTC/BIF
conversion completion, allowing the same unmodified build17 native driver to
observe independent low and high READY states. Its positive run completed
fresh raw pairs with zero TDET writes. This is a slower synthetic timing test,
not evidence that the physical device takes two milliseconds or that default
timing passed. A separate build17 default-timing, no-BIF regression passed
fresh battery-voltage and NTC observations on all eight emulated CPUs.
Native build17's seven startup fault branches and two malformed initial-set
TDET handoffs passed, all with zero TDET write attempts. A later slow-model
post-fresh config test still missed its initial generation and never injected
its requested fault; it is retained as an uninjected failure, not fault coverage.
See evidence/native-bif-build17-faults.json and the separate generation report.

Build18 passed a default 80-microsecond eight-CPU positive run. The explicit
slow fixture then proved that rejected stale generations remain invalid and
recover only after the external synthetic stale condition is cleared. It also
proved that externally clearing timeout, configuration and TDET-ownership faults
does not recover the sticky native error. Post-fresh configuration/TDET drift
invalidated samples, and sustained stale READY kept them invalid while counting
generation rejections. Every run had zero TDET write attempts and no kernel
panic. The eight-CPU execution, source/model hashes and before/after values are
recorded in evidence/native-bif-build18.json. These remain synthetic tests; no
physical timing, calibration or restoration fallback has been established.

Build27 extends raw-pair observation to the enumerated20-word state, including
full HW/SW identity, analog configuration and six factory shadows. See
``BIF-OBSERVATION.rst`` for the atomic diagnostic, exact provenance and limits.
Matching words still do not admit calibrated battery temperature.
