Battery NTC trim and temperature admission audit
================================================

This is an offline audit of the supplied exact Image/preloader and BSP. It adds
no native temperature publication, register writes, charging policy or physical
handoff. BAT_TEMP remains absent. The existing fresh NTC/BIF raw pair proves a
conversion generation and configuration continuity; it does not prove factory
calibration or the board's thermistor characteristics.

What the exact artifacts establish
---------------------------------

The Image SHA256 is
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
``audit_ntc_trim.py Image preloader.bin`` extracts bounded records and emits
``evidence/ntc-trim-audit.json``. It verifies the expected Image digest and unique
preloader record location. ``evidence/ntc-trim-disassembly.txt`` records the
relevant original instructions, not a reconstructed firmware binary.

* Logical IIO channel 3 is BAT_TEMP, hardware channel 3, output 0x108e, request
  0x110e bit 3, 12-bit resolution. Logical channel 14 is VBIF, hardware channel
  11, output 0x109e, request bit 11, also 12-bit. This mapping comes from the
  exact 64-byte channel records at VA 0xffffff80098932c8 and MT6357 register
  records at 0xffffff8009105ef8. It is not inferred from a different upstream
  driver's table. The supplied boot DT specifies ratio 1/1 for both channels.
* ``get_auxadc_out`` at 0xffffff8008b6aab8 requests and masks the hardware output.
  ``mt635x_auxadc_read_raw`` at 0xffffff8008b6b8fc scales a processed reading as
  ``((raw * ratio_numerator * 1800) / ratio_denominator) >> resolution``.
  For this pair that is a separate integer ``raw * 1800 / 4096`` for each.
  The routine then optionally calls the channel's calibration callback. There
  is no separate factory gain/offset operation in this normal conversion path.
* The exact probe installs ``mt635x_bat_temp_cali`` at 0xffffff8008b6b3fc for
  channel 3, and ``mt6357_vbif_conv`` at 0xffffff8008b6b3a0 for channel 14.
  The former is a previous-value/low-voltage diagnostic and possible reread
  path, not a factory trim formula. The latter changes BATON TDET around BIF
  conversion. The diagnostic can reset AUXADC; native code does not copy that
  reset or treat a cached diagnostic fallback as a fresh calibrated reading.
* Actual ``preloader.bin`` offsets 0x38040 and 0x38048 contain adjacent little
  endian 16-bit ``address,value,mask,shift`` records:
  ``113a,95d0,fff0,0`` and ``113c,0055,00ff,0``. They match supplied
  ``vendor/mediatek/proprietary/bootable/bootloader/preloader/platform/mt6765/
  src/drivers/pmic_initial_setting.c`` lines 50–51. Its initialization loop
  passes these fields to ``pmic_config_interface``. These embedded records
  corroborate the intended configuration; they are not a live register read.
  They encode CH3 selector 3 and CH11 selector 1. The second mask does not set
  or prove either compensation control bit in the upper byte of 0x113c.

The normal stock software therefore consumes whatever hardware trim is already
represented in these output words. It does **not** establish that the words are
untrimmed, nor establish the numeric hardware transfer function. Applying an
additional guessed gain/offset correction could double-correct them. Conversely,
the absence of a software correction is not proof that factory calibration was
successfully loaded and enabled on a particular boot.

Readback fields and what they cannot prove
----------------------------------------

The supplied ``kernel-4.14/include/linux/mfd/mt6357/registers.h`` defines:

================  =========================  ================================
Address           Field                      Decode established by header
================  =========================  ================================
0x1008            RG_AUXADC_CALI             low 4 bits
0x10de            SW_GAIN_TRIM               low 15 bits, uninterpreted
0x10e0            SW_OFFSET_TRIM             low 15 bits, uninterpreted
0x113a            TRIM_CH3_SEL               bits 7:6
0x113c            TRIM_CH11_SEL              bits 7:6
0x113c            ADC_2S_COMP_ENB            bit 14, name only
0x113c            ADC_TRIM_COMP              bit 15, name only
0x11a2 / 0x11a4   EFUSE_GAIN/OFFSET_CH4_TRIM  low 12 / 11 bits
0x11a6 / 0x11a8   EFUSE_GAIN/OFFSET_CH0_TRIM  low 12 / 11 bits
0x11aa / 0x11ac   EFUSE_GAIN/OFFSET_CH7_TRIM  low 12 / 11 bits
================  =========================  ================================

These are numeric field boundaries, not documentation of selector encoding,
signedness, gain units, offset units, compensation polarity or shadow validity.
In particular, the CH0/4/7 names do not prove which coefficient bank selector 1
or 3 chooses. Equal selectors would still not prove valid coefficients; the
actual encoded selectors are unequal. PMIC die/buck-temperature calibration
words 0x11ae–0x11b8 describe another sensor calibration and must not be reused
as battery NTC factory gain/offset evidence.

The current BIF diagnostic checks SW trim and ADC configuration before/after
each pair, but does not read these six factory coefficient shadows or analog
calibration field. A future read-only snapshot should include them plus PMIC
identity/revision and the already captured ADC/TDET configuration, with strict
transaction errors, pre/post continuity and reset-epoch invalidation. The pure
``decode_trim`` helper records raw fields and missing words, but deliberately
returns ``calibrated=False`` even for a complete snapshot. No readback values
currently available prove the missing transfer semantics. A future admission
implementation must reference a verified chip/revision-specific transfer model
or independent physical calibration; a caller boolean is not that model.

The public `MediaTek MT6357 product brief
<https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/Genio%20Documents/MTK_MT6357_Product-Brief_v1.0.pdf>`_
identifies AUXADC/BATON functionality and supply pins, but does not define these
trim selectors or gain/offset arithmetic. A targeted primary-source search did
not resolve those semantics. This is an explicit evidence gap, not a claim
that no fuller documentation exists.

When divider cancellation is valid
---------------------------------

For pullup resistance R and ideal voltages N (NTC) and B (BIF), the recovered
stock divider arithmetic is ``R * N / (B - N)``. If both output values are
``G*N`` and ``G*B``, an exactly shared multiplicative G cancels. This requires
the same effective gain, no offset, correct routing and a coherent fresh pair;
equal ADC resolution or nominal 1.8 V full scale does not establish it.

A common additive offset O cancels from the denominator but remains in the
numerator: ``R * (G*N + O) / (G*(B-N))``. Different channel gains/offsets fail
more directly. The exact stock current compensation also subtracts/adds a
physical millivolt correction C from both readings. Then an unknown common
gain leaves ``R*(G*N-C)/(G*(B-N))``: C must be expressed in the same verified
scale. Setting C to zero without proving the actual resistance/current policy
would discard a real compensation term. Separately flooring the two converted
millivolt readings means direct raw-ratio arithmetic is not bit-identical to
stock, even in the ideal common-gain case.

The audit script includes exact rational synthetic examples for all of these
cases, including raw 1400/4089 versus the stock separately floored 615/1796 mV.
These are mathematical counterexamples, not measured calibration vectors.
The existing ``emulate_stock_ntc.py`` and ``stock-ntc-vectors.json`` instead
exercise the original ARM64 board compensation/table arithmetic with explicit
synthetic property inputs; neither suite proves physical ADC calibration.

Concrete native temperature admission design
-------------------------------------------

The eventual implementation needs all of the following, with the result's
deadline bounded by the earliest contributing observation:

1. Existing exclusive ADC/BATON ownership, no uncertain TDET restoration,
   separate fresh NTC and BIF generations, valid ranges and matched pre/post
   configuration. The no-TDET-write restriction remains; see BIF.rst.
2. A verified hardware transfer model for the actual PMIC revision and active
   selector/coefficient/compensation state, including offset/quantization error
   bounds, or a separately validated physical calibration covering both paths.
   Snapshot completeness and historical preloader records alone fail this step.
3. Verified board pullup resistance, actual selected thermistor curve and
   routing, plus runtime-selected COM_FG_METER_RESISTANCE,
   COM_R_FG_VALUE and NO_BAT_TEMP_COMPENSATE. DT defaults/table presence do not
   identify an installed battery. The exact stock path suppresses only COM_FG
   under NO_BAT_TEMP_COMPENSATE; COM_R_FG still participates.
4. Fresh calibrated current with its actual active R_FG/CAR_TUNE configuration,
   adequate temporal coherence and the recovered charge/discharge sign. Reject
   unknown current when compensation is required, rather than assuming zero.
5. Bounded conversion with overflow/divider/range checks, an explicit temperature
   uncertainty envelope and stale/error invalidation at the publication layer.

This design supports a future truthful temperature observation. Charging still
requires the independent cell/charger/thermal limits, watchdog/reset behavior
and fail-closed physical ownership contract; observing temperature alone does
not authorize charge enable.
