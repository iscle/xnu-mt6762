Physical inherited I2C5 entry, capture26
======================================

``mt6762_charger_entry.h`` admits the measured inherited I2C5 state using
44 width-specific reads in each of two passes. It performs no writes and
does not enable a bus or grant charger-control ownership. The captured state
is sufficient for a separately enabled, bounded controller-setup trial.
Physical PSC5425E identity remains unmeasured. Capture31 subsequently
established bus5 post-write behavior; its separate matcher and bounded
read-only mode are documented in ``CHARGER-POSTSETUP.rst``.

Evidence binding
----------------

``audit_charger_entry.py`` checks all235 entries in capture26/peripherals.bin
against its decoded result, frozen peripheral-registers-v3.json and Image33
manifest identity. The record format is version2; the frozen catalog's v3
filename is not a record-version number. Added I2C5 entries are inserted by
group, not appended at the end of the table.

``physical-charger-entry-capture26.json`` contains the36 requested fields
plus9 shared clock/pad/GIC fields, with both original samples and source
hashes. Raw record SHA256:
0fc989e81b363456f1623b040c0bb15bab8c20e52af008fc2f3cbfc5e788611f.
The raw Image identity is27b5e400db43395f64697f3c0943bd92c600bd0062402d072ddb181efaa1f81c.

Relevant observations
---------------------

* TOP I2C parent index2, enabled, with the captured PLL words supporting
 124800000Hz. Shared AP I2C/APDMA gates are clear. Dedicated I2C5, arbiter
 and immediate-mode gates are also clear: INFRA0x100010c8 bits18/19/20.
 The BSP ``clk-mt6765.c`` IFR4 status offset0xc8 and three GATE_IFR4 entries
 establish these fields; the existing shared clocks_stable() does not check
 them. The entry profile checks them before accessing I2C5 or APDMA5.
* GPIO48/49 have function1, input direction and high DIN bits16/17. The
 complete DIN word changed0x000ffa00 ->0x000fea00, solely unrelated bit12.
 The profile masks the two bus pins instead of rejecting this other pin's
 activity. IES/PU bits3/5 are set, PD bits3/5 clear, SMT bits15/17 set;
 shared drive field18..20 is0. No particular drive current is inferred.
* GIC INTID162 (SPI130+32) is pending, disabled and inactive. I2C5 INTR_STAT
 is1, START0, and CONTROL0x28. The pending interrupt and status are
 consistent with a completed transfer, not an active one. The entry check
 accepts exactly the measured controller completion state, leaves pending
 untouched, and checks GIC enable/active and RWP. It does not establish
 exclusive ownership merely because the interrupt is masked.
* I2C5 retains SLAVE_ADDR0xd4 (7-bit0x6a write direction), TRANSFER_LEN2,
 TRANSAC_LEN1, DELAY0xa, TIMING0x418, EXT0x8001, LTIMING0x118, HS0x8000,
 IO_CONFIG0x1a3, TRANSFER_LEN_AUX0, DIV4, TIMEOUT0. These are inherited
 register values; they do not identify the device or reveal transmitted
 data. All16 controller values are checked at their captured16-bit width.
* APDMA5 INT_FLAG/INT_EN/EN are0, CON8, TX/RX addresses, upper address words
 and lengths all0. All10 fields are checked with32-bit reads. The profile
 reads no FIFO, clear, reset, stop or command register.

Producer and consumer integration
---------------------------------

``build_payload.py --native-charger-setup-probe`` requires the existing
native PWRAP/display/passive-capture options. It is off by default and emits
no charger-readonly-probe, charger-verified, charger-control-owned or PMIC
write grant. It requires the kernel's explicit SETUP_ONLY transaction-block
marker, so an older frozen kernel cannot accidentally consume the new option.
No kernel or physical setup trial was built by this change.

1. Producer: all setup grants begin zero. The loader runs
   mt6762_charger_entry_detail() with the width-aware peripheral callback
   before granting bus5. Success publishes ``charger-inherited-probe=1``,
   ``charger-setup-only=1``, ``i2c5-verified=1`` and ``i2c5-hz=100000``,
   alongside the verified parent/dma/pad contract. The entry header is in
   the physical source identity and the existing kernel header snapshot.
   Failure displays all six mismatch fields and commits refusal detail
   ``(address<<32)|(pass<<24)|(width<<16)|15`` in the unchanged trace format.
2. Consumer: mt6762_platform.c maps the eight profile pages with16/32-bit
   reads and barriers. It checks entry before shared gate writes, then
   rechecks immediately before bus5 setup. Mismatch logs the six failure
   fields and rejects bus5 alone, preserving the independent touch path.
   A failed entry cannot be repaired by later shared gate operations because
   its admission result remains false.
3. The inherited bus5 path checks INFRA0xc8 bits18/19/20 before setup,
   after programmed readbacks, and before subsequent transfer admission.
   No dedicated gate, parent or pad write is added. Existing GIC masking,
   controller completion/FIFO clearing and timing writes execute only after
   the entry check. The legacy synthetic paths retain their old behavior.
4. The post-write matcher remains strict: bus5 never selects the touch
   inherited DIV/HS profile. The new capture31-specific bus5 matcher is
   independent of this capture26 entry profile. SETUP/AUX/PROFILE logging captures all
   programmed values, with new SETUP_GATES and SETUP_ONLY lines. Setup-only
   always leaves the engine uninitialized/faulted and keeps its DMA page
   pinned. mt6762_i2c_ready also rejects its explicit setup-only latch, so
   neither PSC nor display-bias transactions can run even if readbacks match
   or another call tests bus readiness.
5. Capture31 now supplies the separate bus5 post-write profile. A future
   explicit producer option can request the existing kernel51
   charger-readonly-probe path within pwrap-inherited-probe. The consumer now
   restricts this physical mode to six fixed0x6a ID3/control1/status0 reads
   in order, after setup admission. It grants neither CE-disable nor
   charge-enable and cannot reach the normal charger-control policy branch.

Entry versus post-write evidence
--------------------------------

At parent124.8MHz / requested100kHz, current initialize_bus writes DIV0x0404,
TIMING0x0419, LTIMING0x0118, HS0, EXT0x8001, IO3, DELAY0xa, TIMEOUT0x190.
Capture26 observes bus5 before those writes. In particular, entry TIMING0x418,
IO0x1a3 and TIMEOUT0 explicitly differ from programmed values. Entry DIV4
and HS0x8000 resembled measured bus0 readbacks, but that resemblance did not
prove bus5 behavior. Capture31's independent XNU log now records the actual
result of these writes, including DIV4/HS8000 and matching other fields.
``CHARGER-POSTSETUP.rst`` binds the new matcher to that evidence. An unsuccessful
setup still leaves bus5 faulted; setup-only remains blocked even on success.

Validation
----------

Run ``python3 tools/mt6762/hardware/power/audit_charger_entry.py`` to regenerate
the fixture from the private capture, then
``python3 tools/mt6762/hardware/power/test_charger_entry.py``.
All six tests passed: real two-pass vectors, complete mapping/read widths,
clock-before-controller ordering (including all three dedicated gates),
unsafe pad/IRQ/controller/DMA refusal in either pass, unrelated GPIO changes,
entry versus setup rejection, and missing-callback/mapping failures. Tests
compile only the small header wrapper with the host C compiler. No kernel
build, phone access, transaction, ownership grant or physical setup result
is claimed by these tests.

``test_charger_setup.py`` adds five tests, including host execution of the
actual platform initialize_bus/readiness/transfer-admission functions against
fake MMIO. Setup-only remains blocked for matching and mismatched readbacks;
the separate read-only mode is restricted to six fixed PSC reads. Entry/gate
failures stop setup, later gate changes block transfers, and the old bus0 and
synthetic bus5 behavior is preserved. ADT tests check zero
initial grants, absent PSC permissions and invalid-option refusal before file
access. Both suites are wired into power/test.sh. Kernel source identity
automatically includes shared tools headers; its existing snapshot mechanism
is tested directly. No kernel-header/IIG input was changed.
