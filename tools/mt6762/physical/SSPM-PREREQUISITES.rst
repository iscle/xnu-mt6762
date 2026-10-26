External SSPM prerequisite capture
=================================

The passive catalog now contains244 entries, adding nine external prerequisite
words to the previous235. Record version2, the4096-byte layout and250-entry
limit are unchanged; six entries remain free. All existing entries and their
relative order are preserved. The additions are32-bit group0 observations,
before groups1..5, and are read on both passes even if their values would fail
a future admission check.

This change does not enable ``sspm-inherited-probe`` or any other handoff
property. It does not access CSRAM0x00110c00..0x00111fff, SSPM
0x10400000..0x1049ffff, protected firmware DRAM, or secure-only DEVAPC AO.
No register writes, commands, acknowledgements or clock changes are added.

Added words and evidence boundary
---------------------------------

================ ================ =========================================
Address          Register         Interpretation boundary
================ ================ =========================================
0x10000040       CLK_CFG_0        AXI source/gate, exact stock descriptor
0x10000090       CLK_CFG_5        SSPM source/gate, exact stock descriptor
0x10006350       SYSRAM_CON       SRAM power fields, BSP semantics only
0x10006358       SSPM_SRAM_CON    SRAM power fields, BSP semantics only
0x1001a010       SRAMROM_SEC_CTRL Region0 permission, exact PL initializer
0x1001a024       SRAMROM_SEC_CTRL5 Region3 permission, exact PL initializer
0x1001a050       SRAMROM_SEC_ADDR Split0/enables, exact PL initializer
0x1001a054       SRAMROM_SEC_ADDR1 Split1, exact PL initializer
0x1001a058       SRAMROM_SEC_ADDR2 Split2, exact PL initializer
================ ================ =========================================

``sspm-prerequisite-registers-evidence.json`` records exact artifact digests,
bounded code/table hashes, BSP sources, and candidate comparison masks. No
candidate is implemented as an admission predicate or labeled physically
validated. In particular, the SYSRAM all-bank awake value0xffff0000 and SSPM
SRAM masked value0x12 are conservative BSP-derived screening candidates. Bank
mapping and physical status behavior still need validation; a different value
must not trigger a repair write or an inferred power grant.

The exact stock SSPM mux descriptor at0xffffff8009051a68 identifies TOP0x90,
source[1:0], gate7, and the parent array at0xffffff80090521a0. Exact preloader
instruction0x224620 writes its stock selection0x01010201. AXI uses TOP0x40.
Capture30 already double-observed enabled MAINPLL settings and INFRA0xc8=0,
which includes the enabled MCU_PM_BCLK gate17. The precise relationship of
that bus gate to every SSPM access is not established by its name. None of
the nine newly added words exists in capture30.

Exact preloader call0x2280ea..0x2280f2 passes0x10dc00 into0x228128. The
initializer splits SRAM at offset0xdc00, enables regions0/3, and gives
region3/domain0 nonsecure access. CSRAM lies within that upper region, but
initialization code alone does not prove current permissions or power state.

Exact tee1 and tee2 are identical. ATF code0x47d94814..0x47d94910 installs
the permission table at0x47d9eaf0. AP/domain0 entries6(SPM),26(SECURITY_AO)
and52(SRAMROM) permit access. The same code makes DEVAPC AO secure-only;
direct NS reads of its permission registers are deliberately excluded.
Source policy must be bound to the firmware actually booted, and must not be
confused with a current permission readback. SSPM firmware's protected DRAM
and EMI preservation are separate requirements, outside this capture.

Use and verification
--------------------

Run ``python3 -m unittest test_peripheral_probe`` from this directory. The
actual C reader is exercised with checked address/width callbacks. The new
regression checks244 entries, sorted groups, unchanged4096-byte/version2 ABI,
zero unused slots, two reads of every new word even for adverse values, and
absence of CSRAM/SSPM/DEVAPC reads or ownership/write grants.

The parent image builder must freeze the catalog with its image identity.
Existing captures require their original frozen catalog; this source update
must not be substituted while decoding an older record. Review the new raw
capture before constructing an entry validator. Any future admission must
recheck current state immediately before access and retain all outstanding
firmware, memory, power and permission requirements.
