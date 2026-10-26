Physical secondary CPU admission
===============================

The default physical image still describes one CPU. The standalone
``mtk_psci_fdt_topology(blob, accessible, boot_mpidr, requested, &out)`` helper
admits an explicitly requested two, four or eight CPU topology only after the
existing full bounded FDT parser accepts the actual runtime blob. Link
``psci_fdt.c`` together with ``../fdt_handoff.c``; there are no libc dependencies.
The caller must retain its existing accessible-memory contract for the FDT.
Failure returns -1 and clears the output; it must not fall back to a fabricated
multi-CPU tree. Do not call it for the unchanged one-CPU default.

The accepted profile is the captured MT6765/MT6762 root identity, all eight
Cortex-A53 CPU nodes at affinities 0..3 and 0x100..0x103, one-cell CPU addresses,
zero size cells, enabled CPUs using PSCI, and the explicit ``arm,psci-1.0`` SMC
binding. CPU node ordering is irrelevant. The boot CPU affinity must be zero;
only RES1 bit 31 and MT bit 24 are accepted (captured raw MPIDR 0x80000000
is valid). U bit 30 denotes uniprocessor and is rejected for this profile. The helper does not authorize idle-state use, clocks, voltages or DVFS.
``cpu-map`` and ``idle-states`` are accepted inert subtrees. Their phandles do not
replace the actual per-CPU reg values used for MPIDR routing.

For the first physical trial select two CPUs, output affinities [0, 1], in the
already active cluster. Four and eight remain later explicit options. Preserve
the kernel's single scheduling processor set even when physical Aff1 differs.
Before each CPU_ON, kernel 54 queries PSCI VERSION, FEATURES for CPU_ON64,
CPU_OFF and AFFINITY_INFO64, and confirms the target is OFF. It admits only
major version 1, supported calls and an aligned nonzero entry. These actual
firmware replies are necessary; the DT alone does not prove the calls work.
Keep the existing cache-clean/DSB and per-CPU startup completion checks. The
GIC driver matches each live redistributor TYPER affinity instead of assuming
that CPU index equals redistributor index.

The MT6762 reset-vector addition in kernel 54 preserves x0 and passes through
EL1 unchanged. At EL2 it requires MMU/data-cache disabled and little-endian
state before arranging the existing EL1 startup. Unsupported state parks the
secondary rather than attempting a speculative transition. The exact dumped
ATF constructs EL2h or EL1h secondary SPSR according to SCR_EL3.HCE, so EL2 is a
real shipped-code possibility. This is not an observation of an actual physical
secondary's CurrentEL.

Exact firmware corroboration
----------------------------

The private audit is ``hardware/native-smp-20261026/{audit.py,evidence.json,
bounded-disassembly.txt}``, outside the source tree. Both original tee1/tee2
have SHA256 e1fa33d9afff0895708a8f214322878fd8b398bca3024006a0695cd770d551c3.
All following offsets are within those dumped files, not physical addresses.

* 0xad44 CPU_ON wrapper validates the target, calls the secondary entry
  constructor at 0xa954, then the on path. At 0xa9fc..0xaa18, SCR.RW/HCE select
  the 64-bit entry SPSR 0x3c5 (EL1h) or 0x3c9 (EL2h). Context is preserved in
  the entry-point argument area.
* 0xada8 returns PSCI version 0x10000. The feature handler at 0xb2e8 consults a
  runtime capability word, which must still be queried on the device.
* The warm-entry-shaped path at 0xd20 calls reset dispatch 0x16788 at 0xd44.
  The dispatcher resolves a CPU-ops table using MIDR mask 0xff00fff0. Its sole
  0x410fd030 entry at 0x1fa60 matches captured primary MIDR 0x410fd034.
* That entry contains reset pointer 0x47d96500. Three adjacent reset/power-down
  function pointers consistently establish link bias 0x47d803c0, mapping the
  reset routine to file 0x16140. At 0x1615c..0x16168 the original instructions
  read CPUECTLR_EL1, set SMPEN bit 6, write it back, then ISB. This link bias is
  a binary inference, not a live ATF load-address measurement.

BSP ATF v1.4 ``lib/cpus/aarch64/cortex_a53.S:166..196`` corroborates reset
SMPEN handling. ``lib/psci/psci_common.c:640..690`` corroborates the SCR-based
secondary mode. ``plat/mediatek/mt6765/plat_pm.c`` on-finish paths describe
cluster coherency restoration, but their exact physical execution and external
interconnect state have not been independently observed. Thus the first trial
uses the same cluster. Do not add native SMPEN/PLL/PMIC writes on this evidence.
A successful PSCI return alone is insufficient: require CPU1 online, its GIC
redistributor admitted, and normal XNU shared-memory work after startup.

Validation
----------

Run ``python3 tools/mt6762/physical/psci/test_psci_fdt.py`` for synthetic admission
and rejection tests. To include a private capture without distributing it, set
``MTK_PSCI_TEST_DTB=/path/to/runtime.dtb``. Eight test groups passed with actual
capture31 (SHA256 2418cd92ebc862f983f15fefd15aeef5163e837ae44f9407af03a26caed53515),
including all requested counts, reordered nodes, duplicate/missing/disabled
CPUs, bad methods/cells/MPIDRs, wrong board, malformed/truncated FDT and cleared
failure output. The initial actual-capture attempt rejected its legitimate
idle-states child; the accepted inert-child list was then corrected and the
actual-capture test passed. This was a parser test failure, not device behavior.

``test_secondary.py`` executes the assembled kernel entry block under Unicorn
in 11 scenarios with explicitly modeled system registers/ERET/barriers. It
checks x0 preservation and rejects unsafe initial state. This does not prove
real EL2 or cache behavior. Parent integration additionally ran the actual
kernel 54 with eight QEMU CPUs: all secondaries online and no panic in its
bounded 20-second test. Physical SMP and physical DVFS remain unproven.
