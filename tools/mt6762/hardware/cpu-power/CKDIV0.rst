Inherited CKDIV code zero
========================

Capture26's twelve stable raw words reveal an overly restrictive observer:
``mt6762_pll_khz`` rejected CKDIV[21:17]=0. The correction admits this specific
inherited undivided encoding. All other previously unsupported divider codes,
PLL bypass muxes, disabled/isolated PLLs and malformed snapshots still fail.
No divider, PLL, rail, firmware ownership or DVFS readiness is changed.

Evidence for the narrow correction
----------------------------------

The conclusion combines three independent kinds of evidence, rather than
copying the stock getter's default branch for every unsupported code:

* Physical acquisition: capture26 contains matching complete observations of
  CKDIV words 0x00010a00, 0x00000aff and 0x00010a00. Each selects its PLL with
  divider code zero. The raw 4096-byte record is version2, complete, and every
  JSON record is independently compared against the raw bytes by the audit.
* Boot firmware: the supplied preloader source deliberately leaves
  ``SET_ARMPLL_DIV_EN`` undefined at ``pll.c:48``, while enabling the PLL mux
  selection. The optional writes of divider codes8/8/10 at lines740..750 do
  not run in that source configuration. At lines621..627 it programs PLL
  control words for the stated 920/1500/600 MHz boot frequencies.
* Exact shipped instructions: the dumped preloader's routine at
  0x2244d2..0x2244eb programs those same control words. Its mux sequence at
  0x2245de..0x2245f7 changes only bits10:9 of 0x102007a0, 0x102007a4 and
  0x102007c0, preserving the inherited divider. Original Thumb instructions
  were replayed against all32 divider inputs; no divider field was changed.
  The exact stock kernel getter at 0xffffff800867bcf0..0xffffff800867be5f
  interprets the observed code0 as unity. Original AArch64 instructions were
  executed using each domain's captured CON1/CKDIV pair.

This establishes a corroborated stock-software interpretation of the actual
boot configuration. It is not an independent electrical frequency measurement
or a recovered hardware specification for every encoding. In particular,
the stock getter also returns an undivided result for several unrecognized
codes; those codes remain rejected in the native observer and offline parser.
The preloader replay models register storage and does not simulate divider
hardware, oscillators, power sequencing or firmware concurrency.

Captured configured rates and rails
-----------------------------------

========== ========== ================ ====================
Domain     CON1       Nominal kHz     Exact stock getter kHz
========== ========== ================ ====================
CPU0-3     811cd89d   1499999          1499500
CPU4-7     0111b13b   919999           919500
CCI        821713b1   599999           599750
========== ========== ================ ====================

CON1 is hexadecimal. The nominal results retain fractional-PCW precision;
stock truncates before division. The preloader's nominal boot targets are
approximately 1500/920/600 MHz. The ARMPLL update bit31 has cleared in the
CPU4-7 observation; it is not part of PCW or either divider.

The two retained PWRAP sample passes agree on VPROC DBG0/DBG1=0x3b2d/0x0043
and VSRAM_PROC DBG0/DBG1=0x3d23/0x0003. Their enabled/stable bits are set.
VPROC's binary selector45 gives 800000 microvolts; VSRAM's selector61 gives
900000 microvolts. Both accompanying Gray-code fields agree with the binary
selectors. These values describe programmed rail settings, not measured
electrical voltages. They do not prove calibrated operating-point suitability
or transfer SSPM control to XNU. The stock C62 maximums remain a separate
policy question; this change does not request them.

Reproduction and validation
---------------------------

``evidence/inherited-clkdiv0.json`` retains full artifact hashes, exact code
range hashes, all32 preloader replay cases, three stock getter results and
raw-derived rail interpretations. The bounded preloader disassembly is in
``evidence/inherited-clkdiv-disassembly.txt``. The corrected physical rate
report is ``evidence/capture26-clock-readback.json``.

With the existing Capstone and Unicorn modules installed::

  python3 audit_inherited_clkdiv.py --image /path/to/firmware/Image \
    --preloader /path/to/preloader.bin --capture /path/to/capture26 \
    --bsp /path/to/workspace --output /private/evidence

The script rejects other stock Image/preloader hashes and mismatched raw
capture data. ``test.sh`` includes three exact captured-regression vectors,
code0 power/mux failures and rejection of all remaining unsupported dividers.
No physical write or kernel build is part of these tests. The sole changed
kernel header is ``bsd/dev/mt6762_cpufreq_protocol.h``.
