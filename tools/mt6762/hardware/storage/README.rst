MT6762 inherited eMMC PIO investigation
=======================================

This package implements an inherited-state MSDC0 read protocol, native wrapper
and read-only BSD adapter for the exact phone's controller. The native path is
tested against a QEMU fixture backed by actual file bytes. No physical storage
access was performed. A physical bootloader, cold initialization and ownership
handoff producer remain unimplemented. Root images currently remain RAM-backed.

Evidence boundary
-----------------

The dumped kernel configuration explicitly selects CONFIG_MACH_MT6765 and
CONFIG_MTK_PLATFORM="mt6765". Its MMC_MTK_PRO driver selects ComboA/mt6765;
this connection does not rely on assuming similarly named SoCs are identical.
Exact stock disassembly corroborates command ARG-before-CMD writes and dsb,
command-status polling/W1C acknowledgement, FIFO offsets/64-byte reads,
DMA controls, pinmux trap behavior, and crypto bypass restoration.

``msdc-audit.json`` records input hashes, function ranges, technical historical
log records and the selected BSP references. ``extract_msdc_evidence.py`` can
reproduce bounded offline disassembly and technical boot records in a new
output directory using pyelftools and Capstone. It excludes card identity,
partition contents and key-register ranges. The historical logs show LK
using 50 MHz DDR, followed by Android reinitialization and 200 MHz HS400;
neither is proof of the controller state at a future XNU handoff.

Observed layout and dependencies
--------------------------------

* MSDC0: 0x11230000, size 0x10000; DT SPI79, hence GIC INTID111. Historical
  Linux IRQ83 is a software mapping and must not be used as the GIC number.
* MSDC0 top timing macro: 0x11cd0000. Timing words at offsets0x00..0x2c
  depend on completed tuning; there are no universal safe constants here.
* GPIO controller: 0x10005000. Trap0x6f0 bits14:13 select mux encoding.
  MODE0+0x3f0 mask0x77777700 and MODE1+0x400 mask0x00777777 use encodings
  0x22222200/0x00222222 when trap==0, otherwise0x11111100/0x00111111.
  Exact stock msdc_set_pin_mode corroborates these masks and branches.
* Electrical pad bank is io_cfg_lt0x10002000, not the timing macro.
  DRV+0: CLK[8:6],CMD[11:9],DAT[14:12],DS[17:15],RST[20:18]. Dumped DT
  default drive values all3; HS200/HS400 use CMD/RST3 and CLK/DAT/DS4.
  Selected BSP pull-up configuration uses PUPD+0x30 mask0xfff value0x401,
  R0+0x50 value0xbfe, R1+0x60 value0x401. IES/SMT functions in this BSP
  are empty for host0: dump-format "should" strings alone must not be
  promoted into verified programming requirements.
* Clock selection: TOPCKGEN0x10000000+0x70, hclk select[1:0]/gate7,
  MSDC0 select[10:8]/gate15. Selected BSP expects selects1 and ungated.
  INFRA0x10001000+0x94 bit2 is the hclk gate; +0xc8 bit9 is the source
  gate, both clear when enabled. Actual source frequency needs PLL decoding,
  not the driver's fixed-frequency array alone. Preserve shared clocks.
* MT6357 VEMC enable0x1988 bit0; VIO18 enable0x1958 bit0. Actual regulator
  table maps VEMC0x1c20 bits10:8 indexes2/3/5 to2.9/3.0/3.3V. Stock
  msdc_emmc_power asks for3.0V. A different msdc header's numeric11 constant
  is not the actual MT6357 voltage selector and must not be programmed.
* Host reset is MSDC_CFG bit2; card reset and power sequences are separate.
  Native inherited mode must never call stock msdc_init_hw: that path resets
  controller/tuning/width and is intended for a full card reinitialization.
* DMA: address high nibble0x8c, low address0x90, control0x98, status0x9c,
  length0xa8. Basic and descriptor paths support high four address bits;
  descriptor checksums cover16bytes. The PIO core never programs any of them.
  Quiescent DMA status does not establish ownership of old descriptors.

Protocol and admission
----------------------

The canonical pure-C implementation is
``bsd/dev/mt6762_msdc_protocol.h``. Zero-initialize its state once and provide
serialized callbacks. The admission callback runs before any MMIO on initial
admission and before later commands. It must establish exclusive controller,
card, IRQ, clocks, rails and tuning ownership from a real handoff, then verify
that these remain valid. It cannot merely return success because ADT flags
exist. Ownership also requires previous Linux/LK DMA and command queues to
be drained, pending media writes completed by their previous owner, and no
other AP/firmware owner still able to submit work.

The narrow consumer requires PIO mode already selected. LK or Android may
leave DMA selected; the consumer does not silently change it. No controller
reset, stop, retuning, card SWITCH, partition switch, queue disable, clock,
pad, rail, crypto-key, DMA, erase or storage-write operation is implemented.
A separate validated handoff producer is still required.

The core independently checks exact supplied CFG/SDC_CFG readback, CFG
MODE/PIO/CKSTB set and RESET clear, 8-bit controller width, INTEN0, no inherited
interrupt status, idle SDC status bits0/1, DMA status bit0 clear, empty RX/TX
FIFOs with no FIFO clear in progress, EMMC51_CFG0 bit0 clear, MTKCQ_CFG2
EN/BUSY bits0/1 clear, and cryptoSWST0x670 low3bits==4. The crypto bypass
check is corroborated by the exact stock completion function; it neither
reads keys nor establishes the plaintext meaning of encrypted Android data.

Initialization sends only CMD13, CMD8 EXT_CSD, CMD13. Actual EXT_CSD must
confirm user-area partition selection(179 low3bits0), card command queue
disabled(15==0), sector count(212..215) equal to the handoff, and bus-width/
HS_TIMING compatible with controller CKMOD. Supported narrow pairs are
SDR8-bit(width2)/HS orHS200 with mode0/1, DDR8-bit(width6)/HS with mode2,
or DDR8-bit/HS400 with mode3. Enhanced strobe is rejected. A failed CMD8
never causes a queue or partition switch. The previous owner must quiesce
the card before initial commands; successful CMD8 corroborates that contract.

CMD13 encodes0x8d with RCA<<16 and requires READY_FOR_DATA plus TRAN state.
CMD8 encodes0x02000888; CMD17 encodes0x02000891. Both transfer512bytes,
set SDC_BLK_NUM1, write ARG then CMD with the platform's completion barrier.
Command status uses0x700; data completion/errors use0xd000. Only observed
completion bits are acknowledged W1C, and acknowledgement readback is checked.
Errors take priority over simultaneous completion. Reads drain64bytes through
sixteen32-bit RXDATA accesses; receiving all512bytes alone is insufficient
without a new data completion and successful final CMD13. Conservative R1
status checks reject error/locked/exception states.

Every read stages512bytes privately; caller output changes only after complete
success. LBA/capacity checks precede MMIO. Timeouts have both an absolute-time
bound and an iteration bound, so a frozen/backwards clock cannot spin forever.
Ownership, state, CRC, timeout, short-data, missing-completion and failed-ack
errors permanently fault the instance. No implicit reinitialization/retry exists.

Native BSD adapter
------------------

``bsd/dev/mt6762_msdc_bsd.c`` registers independent read-only block and character
devices after actual CMD8/status validation. It serializes sector transactions
with a mutex and refuses writes at open, strategy and character entry points.
Block requests require sector alignment, nonnegative block numbers and at most
64KiB; partial EOF preserves accurate residuals. Character reads support
unaligned ranges and use a private512-byte buffer, releasing the mutex before
uiomove so a user page fault cannot recursively deadlock the controller.
One-shot registration publishes readiness with release/acquire ordering; failed
registration removes nodes/major numbers without publishing callbacks.
GIC111 stays masked and no ISR consumes polling completion flags. Virtio and
Qualcomm UFS transports are not involved. Partition windows are not implemented.

Read-only media transport still does not place iOS on the phone. GPT parsing,
authorization of any future iOS partition, APFS image layout and later write/
data-volume support are separate work. Existing Android encrypted userdata
must not be treated as plaintext APFS. No existing partition is modified or
selected for replacement by this investigation.

Validation status
-----------------

``sh test.sh`` exercises the exact header through fake register callbacks:
readback refusal before writes; actual EXT_CSD rejection; byte-for-byte512-byte
reads; overflow/bounds; command/data CRC; timeout/short/missing completion;
dropped final acknowledgement; ownership loss; unchanged failed output;
and refusal to recover a faulted instance. Frozen/backwards time sources and
simultaneous data-error/completion status are also checked. Both host suites
pass with strict C11 warnings. The opt-in QEMU raw-backed fixture is default
absent and provides synthetic inherited state and fault injection. Its QTests
pass; see LAB-MSDC.rst and evidence/qemu-msdc-qtest.json. Native BSD/QEMU runs
add actual guest-side device reads and fault tests. Neither layer validates
physical clock/pad/power readiness, and no physical result is claimed.

Clock admission arithmetic
--------------------------

``bsd/dev/mt6762_msdc_clock.h`` decodes the actual MSDCPLL descriptor found in
the stock ELF at0xffffff80090502c0: CON0 offset0x27c, power0x288, PCW/post-divider
0x280, PCW22bits with8integerbits, post-divider exponent bits26:24. Reference
clock26MHz yields ceil(ceil(26000000*PCW/16384)/(1<<postdiv)). The exact stock
recalc functions corroborate both round-up steps. Require enable bit0, power
bit0 and isolation bit1 clear, and compare stable repeated register reads.
This arithmetic does not measure PLL lock or validate arbitrary analog settings.

TOP source selector1 uses msdcpll_ck directly. The stock driver's hclks array
contains400000000 regardless of actual PLL state; selected preloader source
programs0x820ec4ec, decoded383999878Hz. That source configuration is not evidence
of this phone's current PLL. It demonstrates why a logged nominal400MHz is
insufficient. The exact stock PLL descriptor's minimum-VCO field is1.6GHz
where the reference BSP says1.5GHz; neither minimum is used to synthesize
register programming in this consumer.

Supported conservative controller forms: mode0 divides by2 when DIV0, otherwise
4*DIV; mode1 requiresDIV0 and uses parent; mode2 accepts onlyDIV0(/4) and the
tracedDIV1(/8); mode3 requiresDIV0 and divides by2 when bit22 is set, otherwise4.
Other DDR divider encodings and bit22 outside mode3 are rejected. The stock
set-rate path halves a computed DDR divisor and loses odd intermediate values;
this package does not pretend that inversion is a complete hardware reference.

The decoded card clock is supplied as ``card_clock_hz`` and bounded by actual
EXT_CSD CARD_TYPE196 and HS_TIMING185. VIO18 is1.8V, so HS200 requiresbit4,
HS400bit6, and DDR52bit2.1.2V-only capabilities are rejected. SDR HS uses26MHz
or52MHz limits according to CARD_TYPE bits0/1; HS200/400 cap at200MHz. These
checks supplement stable timing/pad snapshots and completed tuning ownership;
they do not replace those handoff prerequisites.

Native wrapper contract
-----------------------

``bsd/dev/mt6762_msdc.c`` now connects the protocol to the separately owned
read-only BSD adapter. It is compiled only for the MT6762 board; other boards
receive an empty initializer. Default boot has no MSDC activation properties.
Basic required ADT scalars are ``msdc-owned=1``, ``msdc-inherited-verified=1``,
``msdc-sector-count``, ``msdc-rca``, ``msdc-cfg``, ``msdc-sdc-cfg``,
``msdc-timeout-us`` and ``msdc-card-clock-hz``. This narrow wrapper limits
sector count to INT_MAX so its diagnostic integer cannot overflow.

An explicit ``lab-fixture=1`` branch skips unmodeled physical clock/pad/rail
checks. It still requires controller/card protocol admission and GIC111 to
be disabled, inactive, not pending and level configured, with GIC RWP clear.
The lab branch is labeled SYNTHETIC LAB and is not a physical handoff producer.

Physical admission additionally requires all of these assertions, each1:
``msdc-irq-owned``, ``msdc-clock-owned``, ``msdc-pads-owned``,
``msdc-rails-preserved``, ``msdc-tuning-preserved``, ``msdc-card-quiesced``,
``msdc-writes-drained``, ``msdc-sector-addressed``, ``msdc-ocr-verified``,
``msdc-handoff-producer-version``. The preserved ``msdc-ocr`` must have ready
and sector-addressing bits31/30 set. Assertions do not produce the ownership
transfer: a real producer must quiesce other users, drain their work and
capture/verify the state before jumping. No such producer is implemented yet.

Physical register readback additionally requires:

* ``msdc-pad-drive`` equal to one of the exact dumped DT normal/fast encodings,
  matching the actual driver-strength fields; known mux/trap/pulls as above.
  TDSEL mask0x00fffff0 and RDSEL mask0xfffffffc must be zero. Selected BSP
  ``msdc_emmc_power`` calls both setters with flag2 (nonCUSTOM), which writes
  zero to exactly these fields. This is a narrow preserved-stock contract.
* ``msdc-pll-con0/con1/power`` and ``msdc-mainpll-con0/con1/power`` match stable
  repeated PLL reads. The hclk mux selects syspll1_d2, defined by the selected
  provider as MAINPLL/4. MAINPLL must be enabled, reset-bar released, powered
  and not isolated. ``msdc-hclk-hz`` must equal its decoded rate/4. MSDCPLL
  and controller decode must match ``msdc-card-clock-hz``.
* ``msdc-top-tune-0`` through11 match the12fixed top-macro words0x00..0x2c.
  ``msdc-controller-tune-0`` through17 match fixed controller offsets:
  04,b0,b4,b8,f0,f4,f8,fc,100,104,180,184,188,18c,190,194,198,19c.
  These are captures of completed tuning, not values synthesized here.
* PMIC reads confirm VEMC/VIO18 requested enables and actual DA_EN bit15 in
  VEMC_CON1=0x1996/VIO18_CON1=0x1966, with VEMC selector3. The selected
  regulator driver's is_enabled callback uses these actual-enable fields.
  Values are read twice. This is not analog voltage measurement; tentative
  PG_DEB polarity/threshold claims were deliberately excluded.

GIC/clock/pad/tuning/rail admission repeats around commands. Controller reads
are ordered and each protocol write uses dsb sy. No clocks, GPIOs, rails,
GIC enable/ack state, tuning, DMA or crypto registers are written by the
wrapper. Late failure stops future reads without controller recovery.

Read-only sysctls under ``kern.redwood`` are ``mt6762_msdc_ready``,
``mt6762_msdc_fault``, ``mt6762_msdc_last_error``, ``mt6762_msdc_reads`` and
``mt6762_msdc_sectors``. Read counts exclude EXT_CSD and count only completed
media sectors. Capacity is corroborated at initial admission; readiness is
separate and clears on a terminal transport fault. Actual BSD/runtime fixture
results must be recorded separately from host-test evidence.
