Exact LK software-reset sequence
================================

This offline audit executes the retained LK's original instructions at
0x48043274, with RAM-backed registers and modeled logging/delay calls. It
neither resets the phone nor implements a DA write helper. The pinned LK hash,
bounded disassembly and eight branch/preservation test traces are in
``lk-reset-evidence.json``; ``audit_lk_reset.py`` reproduces them.

Original reset operation
------------------------

``mtk_arch_reset(mode)`` calls the following operation, then spins forever.
The values below are code evidence, not a recommendation to write them without
checking the active download-agent state:

1. Write 0x1971 to watchdog RESTART at 0x10007008.
2. Read MODE at 0x10007000 and NONRST_REG2 at 0x10007024.
3. Write ``(MODE & ~0x58) | 0x22000004`` to MODE. This clears bits3,4,6,
   sets EXTEN bit2 and the write key, and preserves other readback bits,
   including ENABLE bit0 and IRQ_LEVEL bit5.
4. Write NONRST_REG2 with only bit13 changed: set for nonzero mode, clear for
   mode0. All other bits, including the low reset-reason nibble, are preserved.
5. Read STATUS at 0x1000700c. Only if zero, read LATCH_CTL2 at 0x10007048 and
   write ``(old & ~0x20000) | 0x95000000``. The audit establishes the exact
   operation; it does not assign an undocumented hardware meaning to bit17.
6. Wait100 microseconds. Read MODE for a diagnostic print.
7. Call0x48005f50, whose own diagnostic string is ``pmic wrap disable``.
   It writes zero to PWRAP_WRAP_EN at 0x1000d004 and waits10 microseconds.
   The latter call0x48042a90 is a thunk to the same microsecond routine,
   not a millisecond delay. Its conversion at0x4804290c multiplies by13 for
   the13MHz timer.
8. Write0x1209 to watchdog SWRST at0x10007014, then spin at0x4804333c.

The supplied platform/mt6765/mtk_wdt.c differs materially: it uses MODE's
AUTO_RESTART bit for power-key bypass, clears ENABLE/IRQ_LEVEL as well, and
has no matching NONRST2 bit13, conditional LATCH_CTL2 or PWRAP-disable sequence.
It is corroborating register/key documentation, not the exact deployed reset
implementation. Do not substitute its different sequence silently.

Recovery routing is separate
----------------------------

The registered reboot-recovery handler first sets the RTC recovery marker and
then calls this reset with mode1; that route is covered in recovery-review.rst.
The reset itself neither writes RTC recovery nor modifies the para partition.
A preinstalled ``boot-recovery`` BCB is consumed by the normal LK path only if
that path reaches its BCB check.

A concrete nearby priority check at0x480038e0 calls0x48042f10 and skips BCB when
the result is2. That getter reads, clears and caches NONRST2's low four bits.
This is a cached boot/reboot selector, not the general WDT boot-reason enum.
This reset's RMW preserves that nibble: setting mode1/bit13 does not clear or
replace an inherited selector2. Other preloader and LK priorities still apply.

DA applicability and remaining proof
-----------------------------------

The exact LK sequence demonstrates a reset mechanism distinct from the observed
DA shutdown operation. A DA implementation could reproduce these bounded
read/modify/write operations only after verifying access widths, preserved
register state, delay behavior and its own quiescence/transport ordering.
The final reset can disconnect USB before a reply, so missing acknowledgement
would not itself establish failure or success. PWRAP is explicitly disabled
before reset; no later DA PMIC access may be assumed safe.

This audit does not establish that the current DA state has the same RGU/PMIC
reset configuration as LK, that a host-paced delay is equivalent, or that the
current preloader consumes bit13 identically. It does not prove recovery entry,
RAM retention, a live AP restart or XNU execution. Do not interpret its passing
software tests as a completed physical reset trial. No new persistent boot
selector, security change, reset-mode substitution or peripheral fallback is
introduced here.

Reproduce with installed Python capstone and unicorn::

  python3 audit_lk_reset.py --lk /path/to/lk.bin --bsp /path/to/workspace \
    --output /private/lk-reset-evidence.json

The tests cover mode0/1, STATUS zero/nonzero and both zero/nontrivial inherited
register values. They execute the original reset and PWRAP-disable instructions,
record each MMIO write/delay in order, and stop at the SWRST write. Peripheral
registers are plain modeled memory; only logging and delay callbacks are
replaced. No phone transport or physical address access is present in the tool.
