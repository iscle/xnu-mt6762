Native CPU/CCI observation
==========================

``bsd/dev/mt6762_cpufreq.c`` is now a native readback module. It has no clock,
voltage, mailbox, SRAM-vote or governor-write path. The earlier offline OPP
selector remains useful for planning only. No physical device execution or
native DVFS transition is claimed.

Admission and reported values
-----------------------------

The common version-1 native handoff must be accepted first. An additional
``cpu-clock-verified=1`` authorizes reads of the initialized APMIXED and MCUCFG
blocks. CPU0-3, CPU4-7 and CCI use their respective PLL CON0/CON1/power and
CKDIV addresses documented in README.rst. A double matching snapshot, PLL
enable, power on without isolation, and source mux selecting that PLL are
required. Reserved divider and postdivider encodings fail. The arithmetic
retains fractional-PCW precision and uses the documented 26 MHz reference;
these are configured nominal frequencies, not frequency-counter measurements.
Bypass sources remain unknown instead of being mistaken for the CPU PLL.

If PWRAP is separately ready, the observer also double-reads VPROC/VSRAM
selector and enable/stable status. ``vproc_programmed_uv`` and
``vsram_programmed_uv`` describe DAC settings, not electrical voltmeter
measurements. VPROC DBG0/DBG1 are 0x14a2/0x14a4; VSRAM_PROC DBG0/DBG1 are
0x19cc/0x19ce. Both DBG1 registers have enable/stable bits 0/1. All registers
are read-only in this module.

``sspm-dvfs-verified=1`` plus ``dvfs-bin=4`` permits reading the exact stock
CSRAM range 0x00110c00..0x00111fff. These properties assert a loader handoff;
they do not initialize firmware or establish a firmware version. The decoder
requires a matching pair of complete snapshots, stock guard words, no pending
EEM flag, valid current indices, and PPM base/limit indices. PVT frequency and
divider methods must match the exact C62 table. Runtime voltage selectors are
imported from the shared table, not replaced with nominal boot values.
Unsupported bins or malformed tables fail without retaining stale validity.

The table starts at CSRAM+0x10. Each domain occupies 36 words: sixteen
frequency-in-MHz/selector words, sixteen postdiv/clkdiv words, and a sentinel
at word 32. Exact stock ``cpuhvfs_pvt_tbl_create`` and table-pointer evidence
are packaged alongside the decoder fixture. Two matching snapshots still do
not prove EEM completion, firmware liveness, or freshness across an ABA
update. Therefore ``dvfs_control_ready`` stays zero. Current-index words at
0x354+4*domain are observations, not sequence acknowledgements. PPM ceilings
are not complete live thermal/current budgets.

Firmware attachment and missing completion
------------------------------------------

The next control step requires a real exclusive handoff from the AP DVFS,
PPM, EEM, scheduler, hotplug and suspend clients. Existing active SSPM firmware
must remain coherent with the inherited rails and all three domains.

Stock ``sspm_alive_show`` at 0xffffff8008809d64 sends PLATFORM IPI ID 0 with
command 0xDEAD, three words, and a one-word acknowledgement. Nonzero returned
acknowledgement is the stock liveness indication. This sysfs *read* actively
sends a firmware command: it has not been exercised under the passive ADB
authorization. Remaining payload words are not initialized in stock; a new
implementation must initialize them explicitly and bound waiting.

Stock ``dvfs_to_spm2_command`` at 0xffffff800867ac10 sends CPU_DVFS IPI ID 1,
four words, polling option 1, and a one-word signed acknowledgement. Commands
0/1 initialize the table/state; command 2 changes cluster online state.
These are state-changing operations, not harmless version queries. They must
not be replayed against active firmware merely to test it.

The supplied BSP mt6765 SSPM layout places the CPU send pin at mailbox 0,
word slot 3, length 4. Mailbox 0 data/control are 0x10450000/0x10451000 in the
actual DT. IN_IRQ is control+0, OUT_IRQ control+4, bit 1 is the CPU pin.
The mailbox-2 CPU notification uses slot 3 at 0x10470000/control 0x10471000;
it carries ring-log bounds. Initialization validates mailbox layout tags,
but ordinary traffic overwrites these tags. Runtime ownership, transport
state and active image compatibility therefore still require a loader
contract and an acknowledged liveness test. No mailbox MMIO is mapped or written by the CPU observer. The separate
SSPM module now performs an explicitly owned, bounded PLATFORM probe; see
SSPM.rst. That response does not initialize CPU-DVFS.

After attachment, any sequence-tagged scheduler vote must be bounded and
checked against actual PLL/CKDIV, shared-rail readback, reported current index,
and the current EEM/thermal/current limits. A stored request word is not a
completed transition. Failed completion must not trigger direct PLL writes or
reduce shared rails. Scheduler integration, SMP demand, CCI mapping, frequency
accounting and firmware-managed idle are additional work before a best
permitted-performance governor is available.

Validation
----------

``test.sh`` tests the exact native decoder header using an independently
extracted stock PVT fixture. It checks runtime voltage import, malformed
selectors/methods/sentinels, preserved output on failure, fractional dividers,
power/isolation/source checks and PPM bounds. These host tests establish
software behavior only. Kernel compilation and emulator evidence are reported
by the parent integration build; ordinary QEMU has no native clock handoff.
