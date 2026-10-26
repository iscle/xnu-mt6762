Capture33 SSPM prerequisite interpretation
========================================

The new clock and SRAM-control observations match the previously recorded
screening values. The five SECURITY_AO zeros do NOT establish that CSRAM is
unrestricted. Keep ``sspm-inherited-probe`` and DVFS ownership disabled; do not
replace the expected security profile with a zero-accepting predicate.

Capture identity and actual loads
--------------------------------

Capture33 is linked to Image38/kernel53 by trace identity
``ab1f5e0df19932df6f498b03af28f543e7029705f50e04dd4ea2309e173a71c1``.
The peripheral record is complete (state2, pass2, last index243). All nine
new entries have valid3 and matching first/second values. The trace reports
entry EL1. Raw record hash, decoded JSON hash and code/artifact hashes are
recorded separately in ``sspm-capture33-evidence.json``.

The exact Image38 loader instruction at0x40086a44 is ``ldr w4,[x4]``. It stores
the result at0x40086a50 and then ORs the pass-valid bit at0x40086a5c..0x40086a60.
The address and width come from the record entry at0x40086a94..0x40086aa0.
Group0 is admitted directly by0x40086a84..0x40086a90. Therefore these zeros
are completed load results, not untouched initialized slots or skipped
prerequisites. No exception was retained for these accesses. That establishes
completion of the access, not visibility of the underlying security state.

================ ============ ==============================================
Address          Both passes  Interpretation
================ ============ ==============================================
0x10000040       0x00020101   AXI source1, gate7 clear
0x10000090       0x01010201   SSPM source1, gate7 clear
0x10006350       0xffff0000   Matches BSP all-bank SRAM screening candidate
0x10006358       0x00000012   Matches BSP SSPM SRAM screening candidate
0x1001a010       0x00000000   Does not match PL region0/domain0 permission1
0x1001a024       0x00000000   Domain0 field0 alone matches; full word differs
0x1001a050       0x00000000   Does not match PL split/enables0x9000dc00
0x1001a054       0x00000000   Does not match PL split0xdc00
0x1001a058       0x00000000   Does not match PL split0xdc00
================ ============ ==============================================

INFRA0x100010c8 remains zero, including MCU_PM_BCLK gate17. MAINPLL's three
captured words remain0xd4800181,0x81150000,0x80000001. Those facts strengthen
the external clock/power screening but do not prove SRAM permissions, SSPM
firmware execution, or mailbox ownership. SRAM field meanings and bank mapping
are still BSP-derived rather than independently characterized hardware.

What zero would mean, and what it does not prove
----------------------------------------------

The matching MT6765 BSP ``tz_sec_cfg.c:tz_sram_enable_region_protection`` calls
bit28..31 clear "disable Region n protection". ``tz_sec_reg.h`` defines
permission0 as secure/nonsecure read/write. Accordingly, IF the five returned
words expose the actual enabled-region and permission state, they describe
disabled region protection with permission fields0. This is a conditional
register interpretation, not proof that the condition holds for EL1 reads.

The exact dumped preloader uses the same addresses and fields. Its literal
at0x2281e4 is0x1001a010; the caller passes0x10dc00 at0x2280ea..0x2280f2.
Instructions0x22815c..0x228176 set all three split words to0xdc00 and enable
regions0/3. Instructions0x228178..0x228198 set low CTRL fields to0xb69;
0x22819a..0x2281ba set the relevant CTRL5 fields to0x01680000. There is no
conditional zero result in that initializer when its ordinary loads/stores
take effect. Thus all-zero EL1 results do not match its configured profile.

There is also historical physical corroboration, not just source inference:
``hardware/mtk-unlock-20261024/expdb-posttrial-complete.bin`` at byte0x698f88
contains the preloader's AFTER log showing split/enables0x9000dc00, splits1/2
0xdc00, CTRL0xb69 and CTRL5 0x1680000. The preceding BEFORE log shows zero.
Other retained boots include CTRL bit31 before/after; its meaning is not
assumed here. These historical logs are not a secure-world observation from
the same boot as capture33, and cannot establish current state.

The exact ATF DEVAPC initializer0x47d94814..0x47d94910 and permission table
at0x47d9eaf0 still corroborate domain0 permission0 for SECURITY_AO entry26 and
SRAMROM entry52. DEVAPC AO itself is secured at0x47d94834. An outer bus-domain
permission does not prove that individual security registers expose their
secure values to nonsecure reads. No exact hardware description or recovered
ATF operation establishes whether these five words read as zero in the
nonsecure view. Nor has a later reset/clear of the SRAM protection registers
been demonstrated. Neither explanation is established by this capture.

Admission consequence and next discriminating evidence
------------------------------------------------------

Classify the five words as ``completed_nonsecure_zero_view_unknown``. Their
stability is useful evidence but is not an access grant. In particular,
CTRL5's zero domain0 field must not be accepted independently of the unknown
region-enable/split and register-visibility state.

The missing discriminator is a trustworthy view of these same five words
after the current secure initialization, paired with the EL1 view and bound
to the exact firmware boot. This can be obtained only through an already
audited read-only secure-firmware query or a separately reviewed same-boot
secure-stage observation; neither mechanism is established here. A nonzero
BOOT_MISC register elsewhere in SECURITY_AO would demonstrate that the block
responds, but would not settle access semantics for the five security words.
Do not use a speculative SMC, permission write, direct secure-only DEVAPC read,
or an unadmitted CSRAM/mailbox access as a substitute.

Mailbox DEVAPC permissions and CSRAM region permissions are separate gates;
these SRAM zeros neither prove nor disprove mailbox permission. The current
observer combines both regions, so it remains disabled until its whole
powered/readable contract is established. This analysis adds evidence and
documentation only; no grants, kernel/header changes or phone operations.
