Bounded retention follow-up, closed by positive capture4
=======================================================

Capture2's256 bytes at0x40084000 are eight repeats of30 bytes0xff followed
by2 bytes0xfb (SHA2565a872f002e1d83f6accf9aef6810f965b3e14213835b1881484d9c2afd1bd6c7).
The DA2 reservation literals and initialized allocator root were verified in
that session. This excludes the demonstrated ordinary allocator collision;
it does not identify the writer of this different pattern.

The exact stock preloader explicitly calls its complex memory test at0x21e386
with address0x48000000 and length0x2000, covering the LK destination rather
than this trace. Its second test uses a dynamically obtained/remapped rank1
address plus0x40000000 and size0x2000; that mapping was not resolved in this
bounded follow-up. These calls are not an exhaustive preloader DRAM write set.

The selected BSP's memory.c corroborates the LK-address test. Its calibration
sources also expose hardware test-agent patterns and ranges, but source options
and address translation cannot substitute for actual-artifact execution proof.
The exact DA1 contains calibration/test-engine code and diagnostic strings;
that does not prove they ran on capture2. The captured connection reports
preloader-mode, not the BROM path on which mtkclient explicitly sends EMI data.
The literal four-byte pattern was not found in the exact preloader or DA1;
a hardware engine or computed pattern remains possible. No causal attribution,
new retention guarantee or proposed relocation follows from that absence.

Capture4 resolves the immediate diagnostic need: its exact Image5 identity,
valid commit fields and runtime reservation readbacks yielded phase254,
previous phase4, detail261. The loader executed at EL1, accepted MIDR0x410fd034
and13MHz timer, then refused the runtime FDT at0x47880000. Detail261 encodes
FDT range error5. That trace survived this particular boot and capture; it
proves loader execution, not the branch into XNU or universal reset retention.
The decoder's general retention flag remains conservative; a successful single
observation does not justify rewriting that flag as a general guarantee.

Further memory-pattern/relocation investigation stopped once that positive
trace identified the concrete parser failure. ``audit_dram_retention.py`` pins
the original artifacts, checks the complete capture2 pattern, emits the bounded
stock call instructions and records selected capture4 facts. It reads local
files only and ships no binaries, private log contents or device operations.
