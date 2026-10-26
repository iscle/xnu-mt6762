Passive inherited SSPM observation
==================================

The next missing physical observation is whether the inherited CSRAM contains
the stock AP table/state representation at all. Captures26 and27 each contain
235 passive register records, including the CPU PLL/divider settings, but no
SSPM mailbox or CSRAM record. Their boot clocks and PMIC selectors therefore
cannot establish an initialized CPU-DVFS controller or permission to attach it.

The previous native observer required ``sspm-dvfs-verified`` to read CSRAM;
the SSPM attachment required ``sspm-mailbox-owned`` before reading mailbox0.
Those gates remain appropriate for the existing consumers, but prevented a
diagnostic from collecting the state needed to investigate that handoff.
``bsd/dev/mt6762_sspm.c`` now has a separate one-shot diagnostic selected by
``sspm-inherited-probe=1`` after the common native platform admission.
No physical image property is enabled by this change.

Scope and admission
-------------------

The new property permits only reads of these already allowlisted mappings:

* CSRAM0x00110c00: guards at0/4/8/c/2a0;144 PVT words at10..24c;
  EEM300..308; PPM320/324; raw voltage words32c..334;
  current indices354..35c; scheduler vote words3a4..3ac.
* Mailbox0 data0x10450000: slots0..6 only; control0x10451000: IN/OUT0/4.
* GICD0x0c000000: ISENABLER7 at11c and ISACTIVER7 at31c.
  Mailbox0 INTID237 is bit13; neither register is written.

Admission must establish those blocks are powered, AP-readable and mapped as
device memory. It grants no mailbox pin/IRQ ownership, firmware identity,
reserved-memory preservation, clock/PMIC control, or table validity. The
observer does not read the protected SSPM DRAM image, follow raw pointers,
load firmware, inspect mailbox2, clear interrupts or send a PLATFORM command.
Its callback interface has no write operation. MMIO returning an external
abort or hanging the bus remains a platform concern; a software read-count
bound is not a hardware timeout guarantee.

The diagnostic mode returns before the active transport, including when an
input handoff mistakenly also supplies ``sspm-mailbox-owned``. It runs once
and creates no worker. Existing active transport behavior is unchanged when
the diagnostic property is absent. No existing kernel header was modified;
the shared helper lives in this tools directory.

There are exactly174 whitelisted32-bit words per pass and exactly two passes,
with no retries. A failed read discards the entire pair. Stability is reported
separately for guards, PVT, EEM, PPM, raw voltage, current indices, votes,
mailbox and GIC state. A stable pair emits one raw copy; a changing pair emits
both complete copies. This is repeated-read evidence, not an atomic snapshot
or protection against an ABA update. Raw pending traffic remains pending.

Exact stock evidence
--------------------

``audit_sspm_observer.py`` pins Image SHA-256
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b and symbol ELF
643474799f7c300f2d3c7f5130f697ee359929f13db0750f4dd7b9d648af14fc.
Per-span/source/capture hashes accompany ``evidence/sspm-observer-evidence.json``.

The exact ``init_cpuhvfs_debug_repo`` at0xffffff8009619f00..9f78 backs up
CSRAM, writes the four initial guards at9f48, clears2a0..13ff through the
9f4c call, writes guard2a0 at9f60, and initializes PPM320/324 to15 at9f64.
Unicorn execution of these original instructions, with modeled memory-copy,
zeroing and ftrace callbacks, reproduces the guards, PPM defaults and zero
EEM/index/vote words without executing any CPU IPI or SSPM firmware. It leaves
the PVT region unchanged. Thus guards and quiet state alone cannot distinguish
an initialized controller from an AP-prepared repository.

``cpuhvfs_pvt_tbl_create`` at0xffffff8009619b24 maps0x00110c10,size240,
at9b74..9b84 and creates the PVT representation. This observer checks exact
C62 frequencies, methods and selector representation using the existing native
decoder, but describes a match only as ``c62_representation``. This is not a
proof of the active silicon bin, EEM completion, calibrated voltage or firmware
acceptance. Pending EEM and malformed current indices remain visible even when
the table representation matches.

The current-index getter at0xffffff800867b230 reads354+4*domain. The raw
voltage getter at0xffffff800867b304 reads32c+4*buck. Neither supplies age or
an acknowledgement. The vote writer at0xffffff800867b4f8..b5dc writes
3a4+4*domain with index[3:0]/counter[11:4]; no sequence echo is checked.
Raw voltage words are deliberately not labeled measured voltages or assigned
units by this new observer. Separate PMIC selector readback remains necessary.

Mailbox0 slot provenance is the exact PLATFORM/CPU descriptors at
0xffffff8009846a70/0xffffff8009846ac0 in ``evidence/stock-sspm-layout.json``.
The stock read path0xffffff80088095b0..9614 copies slot memory without a
status write. The polling routine reads OUT_IRQ at0xffffff80088096dc and
acknowledges separately with a store at0xffffff8008809704; the interrupt
handler likewise reads at0xffffff8008809b88 and writes at9ba0. The diagnostic
implements only reads. Empty IN/OUT or a disabled/inactive IRQ cannot transfer
AP ownership or identify the resident firmware.

The BSP preloader's ``bldr_load_sspm_part`` starts firmware and publishes its
reserved-memory pointer through GPR0. Its load path protects region3 against
ordinary AP access on a normal boot. Those are reference-source requirements,
not an active-image identity or permission observation. This change does not
read that protected region or claim it is preserved from the XNU allocator.

Validation and use
------------------

Run ``./test.sh``. The exact native observer is tested with every one of348
possible read failures, every one of174 changing words, exact whitelist
coverage, output preservation, zero SRAM, invalid PVT, pending EEM/IRQ/traffic
and malformed current indices. The six parser tests reject truncated,
duplicated, missing, out-of-range, improperly padded and inconsistent records.
These tests do not execute physical MMIO or firmware.

After an explicitly admitted physical capture, decode the retained kernel log::

  python3 decode_sspm_observation.py /path/to/xnu-log.bin --output /path/to/sspm.json

The parser hashes its complete input and requires the end marker and all raw
words. It distinguishes omitted identical pass2 data from two supplied passes.
It never emits readiness or ownership. Reproduce the stock code evidence::

  python3 audit_sspm_observer.py --image /path/to/Image --elf /path/to/stock.elf \
    --bsp /path/to/workspace --capture-root /path/to/trace-boot-20261025 \
    --output /private/output

The first physical result can distinguish absent/malformed/changing repository
state from a matching stock representation, and reveal inherited traffic.
Neither result permits replaying INIT_PTBL/INIT_STA. Actual DVFS still requires
the active firmware identity, preserved memory and EMI access, exclusive AP
clients/notification ownership, calibrated table/thermal/current limits and a
verified transition/failure path. ``dvfs_control_ready`` remains false.
