NTC trim initialization: exact-artifact follow-up
===============================================

This bounded offline investigation does not resolve factory-calibrated NTC
admission. It does establish which initialization code is present, and closes
the unsupported assumption that the selected preloader copies AUXADC factory
coefficients in its ``pmic_efuse_sw_load`` path. No native behavior, PMIC state,
charging policy or phone contents were changed. Read alongside ``NTC-TRIM.rst``.

Reproduction and provenance
---------------------------

``audit_ntc_init.py`` requires Python, Capstone and pyelftools. Run::

  python3 audit_ntc_init.py --image /path/to/Image \
    --preloader /path/to/preloader.bin --stock-elf /path/to/stock.elf \
    --bsp /path/to/workspace --output /new/output/directory

The script rejects mismatched exact-artifact hashes, validates GFH load geometry,
extracts five small Thumb ranges and four named stock functions, and records
only relevant configuration records. ``--bsp`` is optional and adds source
hashes plus an exact comparison of the 131-record PMIC initialization table.
The checked-in ``evidence/ntc-init-audit.json`` and
``evidence/ntc-init-disassembly.txt`` were generated this way. The existing REA
firmware/native providers were unavailable; this uses the documented bounded
format-aware fallback, without changing provider configuration. No OTP contents,
private identifiers or other partition payloads were collected.

Artifact digests are in the JSON. The original preloader has GFH_FILE_INFO at
file 0x800, load address 0x200f10 and content/jump offset 0xf0. Thus entry is
0x201000, and the code's linked VA minus file offset is 0x200710. ARM entry
transitions to Thumb routines; the recovered PMIC routines below are Thumb.
Their names are matched to source and call behavior, not an embedded symbol
map. Stock kernel names come from the recovered original ELF symbol table;
function ends use the next distinct symbol and are explicitly labelled so.

Preloader: what actually executes on this path
---------------------------------------------

* The direct call at VA 0x223c62 targets PMIC initialization at 0x224d58.
  Its instruction at 0x224d72 loads a literal whose file location is 0x246c0,
  pointing to ``No EFUSE SW Load`` at file 0x2f449. The following BLX at
  0x224d74 prints it. This is a real instruction path, not merely a string
  found somewhere in the image. It agrees with ``EFUSE_SW_LOAD 0`` in the
  selected mt6765 preloader ``pmic.c``. The disabled reference branch concerns
  unrelated fields at 0x0d3a/0x0d46/0x0d2a, not AUXADC gain/offset.
* Reference ``pmic_efuse.c`` itself has its OTP-read body under ``#if 0``.
  That source fact is not a global binary claim that all possible firmware
  OTP operations are absent. Neither fact establishes how PMIC hardware
  transfers factory fuses to shadow registers at power-on.
* A later call at 0x223dcc reaches ``pmic_init_setting`` at 0x224f80. The loop
  compares its index with 0x83, loads 8-byte records from VA 0x238610 (file
  0x37f00), and calls 0x22470c with address/value/mask/shift. All 131 records
  exactly match the supplied mt6765 ``pmic_initial_setting.c`` table. This is
  stronger evidence for that table than matching only the two selector rows.
* The setter at 0x22470c reads the old word, clears ``mask << shift``, ORs
  ``value << shift`` and writes it. Read/write failures are returned, but the
  initialization loop ignores the return and performs no confirming readback.
  Static execution of this path therefore does not prove successful physical
  register programming.
* The table sets 0x1008 low nibble to 1, 0x113a under mask 0xfff0 to 0x95d0,
  and 0x113c under mask 0x00ff to 0x0055. This preserves both upper compensation
  controls at 0x113c and selects CH3=3 / CH11=1. There are no table writes to
  SW gain/offset 0x10de/0x10e0 or the six factory shadows 0x11a2..0x11ac.
  The analog field named CALI=1 is not a decoded factory-valid flag.

Stock kernel probe and reset
---------------------------

Exact ``mt635x_auxadc_probe`` at 0xffffff8008b6af28 parses channel ratios and
averaging, registers IIO, then tests PMIC model 0x57 and installs the existing
BAT_TEMP/VBIF/DCXO callbacks at 0xffffff8008b6b220..0xffffff8008b6b254. This
routine has no call that copies factory AUXADC coefficients or verifies their
hardware activation. Its IMIX resistance calibration branch is a different
logical channel, not NTC factory gain/offset. The supplied kernel-4.14 reference
probe calls ``pmic_auxadc_chip_init``; that reference path must not be silently
substituted for the observed artifact's different implementation.

The exact function named ``mt6359_efuse_probe`` also supports the MT6357 match
structure. It registers a read-only nvmem read callback. Its probe/read routines
are an OTP access mechanism, not an AUXADC trim loader: no recovered path here
copies results to the ADC coefficient shadows. This does not prove that an
unknown consumer elsewhere cannot read OTP. The audit does not execute the
callback or access any OTP contents.

``auxadc_reset`` at 0xffffff8008b6aea4 walks the selected reset table at
0xffffff8009106010. Its four address/mask/value records are::

  0x0f90 / 0x0009 / 0x0009
  0x0f90 / 0x0009 / 0x0000
  0x110e / 0x0080 / 0x0080
  0x111a / 0x0400 / 0x0400

There is no software coefficient reload or calibration-validity readback in
this reset routine. Whether the hardware reset itself reloads or preserves a
particular shadow is unknown. Consequently a future calibration observation
must expire on reset or uncertain reset ownership; unchanged SW trim alone
cannot preserve that claim.

Remaining boundary and concrete next proof
-----------------------------------------

Preserving stock-like register values can avoid gratuitously changing the ADC
transfer function, but cannot establish that function is factory calibrated.
The bounded missing facts are still selector-to-bank mapping, the meaning and
polarity of 0x113c bits 14/15, coefficient encoding/units, and the PMIC's fuse
shadow loading/validity/reset behavior for the actual revision. Header names,
nonzero coefficients, matching a preloader table, and a producer's boolean do
not supply those semantics. There is no reason here to add a second software
correction, which could double-correct hardware output.

A useful future read-only handoff snapshot would include the previously listed
trim/configuration words and PMIC revision, strict transaction status, pre/post
continuity and a reset epoch with exclusive ownership. It would document
preserved state, not admit calibrated temperature on its own. Admission still
needs revision-specific hardware documentation or independent physical transfer
validation covering both CH3 and CH11 and their offset/error bounds. The
independent board/thermistor/current-compensation requirements in
``NTC-TRIM.rst`` also remain. No additional broad source search or speculative
native register write is justified by the evidence recovered here.
