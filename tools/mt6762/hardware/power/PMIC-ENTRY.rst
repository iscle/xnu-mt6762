Physical MT6357 gauge and ADC entry observation
=============================================

The inherited PWRAP probe previously returned before gauge/ADC admission and
read only PMIC keys/reset and rail words. Captures 26 and 27 show PMIC ID 5730
and matching rail/key samples in two passes, but none of the gauge calibration,
latch or ADC words needed to assess a physical gauge handoff. A working PWRAP
transport does not establish channel ownership or measurement freshness.

``mt6762_pmic_entry.h`` and ``pmic_entry_probe`` in ``mt6762_power.c`` now add a
bounded observation to that existing read-only probe. It performs two sequential
passes over 13 ordinary 16-bit words. Each pass checks the MT6357 hardware-ID
family before continuing. The API has no write callback; a transport error or
wrong ID stops the probe with no retry. A failed pass cannot replace the output
of an earlier complete pass. Existing PWRAP transport failures remain sticky.
The probe runs only with ready, read-only, unfaulted PWRAP, and cannot start the
normal battery policy, gauge thread, conversion requests or charger control.

The address allowlist is:

* 0008: hardware ID.
* 0c0c: BM_TOP_CKPDN_CON0, including gauge clock gates bits 3 and 4.
* 0d08: FGADC_CON0, including FG_ON bit 0.
* 0d0a: FGADC_CON1, including existing latch/command status. Reading it does
  not acquire or clear a latch.
* 0c8e/0c90: hardware gain/offset efuse shadows.
* 0d94/0d96: manual offset adjustment and hardware gain configuration.
* 0e08: BATON_ANA_CON0, detector enable bit 0 and absence bit 1.
* 108a/108e/109e: previous battery-voltage, thermistor and BIF ADC result words.
* 1236: AUXADC_CHR_TOP_CON2, including BATON_TDET_EN bit 1.

No current/CAR/NTER latch data is read outside the existing owned coherent
protocol. The continuously adjusted hardware offset at 0d92 is not included
as a fixed calibration value. No request/SET/CLR address is included: the BSP
defines AUXADC_RQST0 at 110e, SET at 1110 and CLR at 1112. A ready bit in an ADC
output can describe an old conversion. Equal consecutive raw words do not
prove fresh measurements, coherent state, exclusive ownership or calibration.
The log explicitly prints ``measurement_valid=0 ownership_grant=0`` after a
complete pass. Successful observations never set any admission flag.

Source evidence and limits
--------------------------

``audit_pmic_entry.py`` verifies every address against the supplied BSP's
``kernel-4.14/include/linux/mfd/mt6357/registers.h`` and records source line
numbers and hashes in ``pmic-entry-evidence.json``. The BSP IIO ADC function
``get_auxadc_out`` separately writes the request register and repeatedly reads
the output/ready word (``drivers/iio/adc/mt635x-auxadc.c``, lines 373-410). This
supports reading an existing output word without requesting or consuming a
conversion; it does not establish that the inherited result is fresh.

The matching stock Image SHA-256 is
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
Retained disassembly provides the more specific behavioral evidence:

* ``evidence/gauge-protocol-disassembly.txt``: pre/post gauge update at
  ffffff8008a84e08/ffffff8008a84ed0 uses 0d0a for the modern latch protocol.
* ``evidence/battery-presence-disassembly.txt``: battery_exist_get at
  ffffff8008a87464 reads 0e08. Its absent-battery path pulses 114a bit 3; this
  observer does not reproduce that write or infer battery presence itself.
* ``evidence/ntc-compensation-bif-disassembly.txt``: instruction
  ffffff8008b6b3d8 selects 1236 before the stock BIF TDET modification. The
  observer reads the inherited word without changing/restoring TDET.
* ``evidence/gauge-sysfs-coefficients.json``: active R_FG and CAR_TUNE live at
  gauge-object offsets 110/114; car_tune_value sysfs reads manufacturing
  result offset 11c. That sysfs value cannot supply the active coefficient.

These are offline source/disassembly conclusions plus earlier captured PMIC
observations, not a physical run of the new probe. The configured native REA
provider was unavailable; this pass reused the previously captured disassembly
and original-code evidence rather than claiming new native-engine execution.

What a subsequent capture can decide
------------------------------------

The new record can establish whether the inherited gauge is enabled and its
clocks open, whether another command/latch is already present, the five actual
configuration words required by ``mt6762_gauge.c``, detector/TDET state, and
whether old ADC result words are readable. A disabled clock or occupied latch
is evidence to retain, not a request to reset or clear anything.

Matching words still leave exclusive gauge/ADC ownership unresolved. The
separate ``GAUGE-BASELINE.rst`` investigation now establishes a reproducible
fresh native startup pair R_FG=100/CAR_TUNE=1000 from exact, present live DT
cells and the original stock initialization code. Its standalone validator
rejects missing, malformed, ambiguous or disabled profiles rather than using
historical values as a fallback. This does not reconstruct a previous mutable
Android object, validate hardware shadows, or confer ownership; none of the
baseline validator's results is consumed by this PMIC observer. Fresh ADC
requests and gauge latch writes must remain outside this probe.
Fresh calibrated temperature/BIF compensation,
PSC identity and CE-disable readback, and a functioning charge policy are still
separate missing steps. Neither current nor signed accumulated charge alone
establishes remaining capacity/SOC. Stock's constant 25 C temperature_get is
unsuitable for charging protection; the recovered NTC path is documented in
``GAUGE.rst`` and remains separately gated.

Validation
----------

``sh tools/mt6762/hardware/power/test.sh`` includes independent exact allowlist
tests, wrong-ID rejection, every partial-read failure, output preservation,
busy/disabled gauge state, and old/zero ADC words. A second harness compiles
the actual kernel probe functions and verifies the read-only gate, exactly two
passes, every failure position, and immediate stop without retry. Both pass
alongside the existing charger, ADC, coherent gauge, BIF and expiry tests.
No kernel header/IIG input was modified; no kernel build or phone operation
was performed for this change.
