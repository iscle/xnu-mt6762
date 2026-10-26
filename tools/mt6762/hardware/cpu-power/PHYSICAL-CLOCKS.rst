Physical inherited CPU clock observation
========================================

This bounded review uses the exact dumped kernel and the supplied MT6765 BSP.
It adds only an offline parser; it performs no device access or kernel change.
REA native providers were unavailable, so existing bounded stock disassembly,
Capstone/Unicorn, and BSP source are the evidence. Artifact hashes and precise
source/function locations are in ``evidence/clock-handoff-provenance.json``.

The next physical observation
-----------------------------

Capture22 contains UNIVPLL, MAINPLL and MSDCPLL observations, but none of the
following twelve CPU/CCI words. All are ordinary 32-bit clock configuration
or power readback registers; the supplied clock driver uses normal read/modify/
write operations, not interrupt-acknowledgement or clear-on-read accesses.
No frequency, power, reset, divider, mux or rail write is needed to read them.

======== ========== ========== ========== ==========
Domain   CON0       CON1       Power      CKDIV
======== ========== ========== ========== ==========
CPU0-3   1000c21c   1000c220   1000c228   102007a0
CPU4-7   1000c20c   1000c210   1000c218   102007a4
CCI      1000c22c   1000c230   1000c238   102007c0
======== ========== ========== ========== ==========

Addresses are hexadecimal. The actual stock DT supplies APMIXED=0x1000c000
and MCUCFG=0x10200000. BSP ``clk-mt6765.c`` descriptors identify CON0, power,
PCW and postdivider fields. ``cpufreq_v1/src/mach/mt6765/
mtk_cpufreq_platform.c`` identifies CKDIV offsets and maps CPU0-3 to ARMPLL_L,
CPU4-7 to ARMPLL and CCI to CCIPLL. No generic DT frequency is substituted for
an observation of this unit.

``decode_clock_snapshot.py`` consumes the already decoded peripheral JSON::

  python3 decode_clock_snapshot.py /path/to/capture/peripherals-result.json

It requires completed two-pass acquisition, exactly one record for each word,
width four, both valid bits, equal unsigned values, and the stable marker. It
then applies ``mt6762_pll_khz`` admission: PLL enabled, power on and isolation
off, source mux selecting this PLL, nonzero PCW, postdivider codes 0..4 and
CKDIV code 0 (inherited boot encoding), 8..11, 16..20 or 24..29. Missing, malformed, duplicate, unstable,
disabled or bypassed domains remain unknown. Two equal passes are not atomic
and do not exclude an intervening change. A successful parse grants nothing.

The nominal calculation retains PCW fractional precision with a 26 MHz
reference. Exact stock ``get_cur_phy_freq`` at 0xffffff800867bcf0..be5f instead
truncates to integer MHz before applying divisors. The parser reports both
values separately; neither is a frequency-counter measurement. Stock's
fallback for reserved encodings is not copied into the native admission.

Four separate PMIC status words
-------------------------------

The established PWRAP diagnostic can separately double-read these ordinary
MT6357 status words. They are PMIC register addresses, not CPU MMIO addresses.

* VPROC DBG0=0x14a2: binary selector bits 6:0; bits 14:8 are Gray code.
* VPROC DBG1=0x14a4: enable bit 0, stable bit 1.
* VSRAM_PROC DBG0=0x19cc: binary selector bits 14:8; bits 6:0 are Gray code.
* VSRAM_PROC DBG1=0x19ce: enable bit 0, stable bit 1.

``include/linux/mfd/mt6357/registers.h`` provides addresses and fields.
``drivers/misc/mediatek/pmic/mt6357/v1/pmic_api.c`` uses ordinary
``pmic_read_interface`` getters for selector/enable/stable, without clearing
or acknowledging the status. The CPU platform conversion is
``518750 + selector * 6250`` microvolts. Require matching read pairs and
both enable/stable bits before reporting a programmed selector voltage.
This is not an electrical voltage measurement. These BSP semantics have not
yet been corroborated by the four physical values on this XNU boot path.

Established integration limits
-------------------------------

The native CPU observer is already called, but the physical builder supplies
no ``cpu-clock-verified`` property. Its single initial diagnostic uses
``printf``; the retained physical diagnostics use ``kprintf``. Passive loader
samples and the existing retained PWRAP diagnostic are therefore the smallest
next observation without enabling an unproven native handoff.

Exact stock evidence selects C62/bin4: CPU0-3 maximum 2001000 kHz and CPU4-7
maximum 1500000 kHz. Generic DT values 2301000000/1800000000 do not establish
this unit's permitted operating points. All three domains share VPROC1 and
VSRAM1 in the platform source. A maximum-performance controller still needs
current EEM calibration, thermal/current limits, shared-rail aggregation,
exclusive CPU-DVFS/notification ownership and observed transition convergence.
The existing ``FEEDBACK.rst`` explains why the stored vote sequence and raw
current index are not a sequence-matched completion acknowledgement. No
SSPM data or mailbox state was present in capture22; liveness, initialization
and table compatibility therefore remain unknown on this handoff.

The physical builder also explicitly emits one CPU and ``cpus=1``. No physical
secondary CPU failure was observed in this audit. The generic PSCI start path
already exists. Runtime topology, PSCI query results and per-CPU interrupt
coverage are still required evidence before changing the physical CPU count;
no direct power-controller programming is justified by this audit.

Capture26 follow-up: the added physical observations identified inherited
CKDIV code 0 on all three domains and both programmed CPU rail selectors.
``CKDIV0.rst`` records the exact preloader replay and narrow decoder correction;
the capture22 absence above remains a historical finding.

Offline validation
------------------

``evidence/clock-decoder-validation.json`` records 2568 comparisons against
the compiled native decoder header, 225 executions of the exact stock getter
in Unicorn using synthetic register RAM, and ten malformed/missing acquisition
cases. All passed. Stock's earlier rounding differs in 150 of the 225 cases;
for example PCW 0x55555 yields 554000 kHz from stock and 554666 nominal kHz.
These tests establish parser/arithmetic behavior, not physical clock behavior.
