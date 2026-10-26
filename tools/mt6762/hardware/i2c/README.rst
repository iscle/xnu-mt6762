MT6765-family I2C transaction core
================================

This portable core is connected to XNU's native platform worker. Emulated
FIFO/DMA transactions and input events have run; physical capture20 reached
the inherited I2C0 setup check and refused its readback before any touch
transaction. Physical touch communication and gestures remain unverified.

Evidence: the supplied stock DT's mediatek,i2c_common node selects version2,
DMA support2 (33-bit), clock divider5, LTIMING and MT6765 counter constraints.
Register definitions and transfer ordering are from the supplied BSP
kernel-4.14/drivers/i2c/busses/i2c-mtk.{c,h}. The stock kernel is4.19 and
its timing/clock implementation must be reconciled before native activation.

I2C0 is0x11007000, APDMA0x11000080, SPI84; I2C5 is0x11016000,
APDMA0x11000580, SPI130. SPI numbers require +32 for architectural INTIDs.
Actual AXS touch is bus0/address0x3b; panel bias and PSC5425E are bus5 at
0x3e and0x6a. No bus scanning or device writes were used to establish these.

The core handles one write, one read, or write followed by repeated-START
read to the same7-bit address. Up to8bytes uses FIFO; longer transfers use
APDMA with a dedicated33-bit-addressable coherent buffer. This permits the
AXS controller's single32-byte read without inventing a register prefix.
V2 AUX_LENGTH is0x44, MCU_INTR is0x40. Controller accesses are16bits and
APDMA accesses32bits. A controller error overrides a simultaneous completion.
Every wait is bounded; failed transactions fault the context and do not
publish partial receive data or automatically reset/retry a charger write.

Required native integration
---------------------------

* Claim exclusive controller/APDMA ownership, enable the correct parents and
  gates, establish IO rail/pinmux and configure verified standard/fast-mode
  timing. The core accepts at most400kHz and preserves those timing registers.
  The observed DT divider alone does not identify the input clock frequency.
* Map device registers with Device memory attributes. Supply ordered16/32-bit
  MMIO and a real full-system barrier, plus a functioning microsecond timer.
* Allocate physically contiguous coherent DMA memory, pin it, use its bus
  address (never a kernel virtual address), and validate the entire allocation
  below8GiB. If memory is cacheable/noncoherent, this interface is insufficient:
  add direction-aware cache clean/invalidate and ownership transitions first.
  Establish whether this APDMA path bypasses or needs the platform IOMMU.
* Serialize the entire transaction, including power register read/modify/write.
  Verify START and APDMA idle before ownership transfer. After a failure keep
  the DMA buffer pinned and inaccessible to reuse until DMA has been stopped
  and the reset/clock/power state has been re-established by a proven sequence.
* Hook polling into a worker, not a long interrupt-disabled section. Add
  the controller's GIC source to the ownership contract: it must stay masked
  in the GIC while this polling core is used. Peripheral event enable matches
  the BSP's0x12f mask and is cleared on completion/failure; raw status
  visibility with all peripheral events disabled is not assumed. Add
  interrupt operation only after the GIC routing and interrupt acknowledgments
  have been tested. Verify normal reads before any charger or bias writes.

Neither successful host tests nor setting ``initialized`` supplies these
prerequisites. The native integration checks inherited clock/IRQ/pad state,
allocates a private coherent DMA buffer and polls from a worker. Physical
DMA and reset recovery remain unaccepted. Run ``bash test.sh`` for host tests.

Measured setup readback
-----------------------

Capture20/kernel38 programmed the stock-style DIV0x0404 and HS0 values, then
read DIV0x0004 and HS0x8000. TIMING0x0419, LTIMING0x0118, IO3 and the inherited
clock checks matched. ``native_setup.h`` gives the admitted physical I2C0
profile these exact readback expectations; programming is unchanged. The
emulated profile retains its original expectations. Unknown profiles,
unmeasured dividers and other mismatches fail. This observation does not
establish the undocumented bits' meaning. Kernel42 includes this correction;
its physical transaction result is pending. See
../display-touch/physical-build38-evidence.json.

Clock dependency evidence
-------------------------

Both actual DT controller nodes reference infracfg_ao (phandle0x25) clock
ID11 as ``main`` and ID38 as ``dma``. The supplied MT6765 binding header maps
these to CLK_IFR_I2C_AP and CLK_IFR_AP_DMA. In clk-mt6765.c they resolve to:

* I2C AP gate: infracfg_ao base0x10001000, bank0 bit11, gate-set0x80,
  gate-clear0x84, status0x90; parent ``i2c_ck``.
* APDMA gate: same base, bank1 bit18, gate-set0x88, gate-clear0x8c,
  status0x94; parent ``axi_ck``. These gates use active-high disable bits,
  so enabling uses the clear register, not an RMW of the status register.
* I2C parent selector: topckgen base0x10000000, CLK_CFG_6 offset0xa0,
  selector bits2:0, gate bit7, set/clear0xa4/0xa8, update bit24 in
  CLK_CFG_UPDATE. Encodings0..4 select clk26m, univpll3_d4, univpll3_d2,
  syspll1_d8, syspll2_d8 respectively. Remaining encodings are not defined.

The divider property5 is then part of the I2C controller timing computation.
It must not be multiplied by an assumed PLL rate. Parent changes affect other
I2C consumers, including firmware/SSPM-owned channels. Preserve and decode the
current parent initially; any reparenting needs explicit ownership, inactive
transactions, the update handshake and new timing values for every consumer.
The clock source's actual rate must come from its verified PLL configuration.

The BSP also defines I2C5/arbiter/immediate gates (IDs58..60, bank2 bits18..20),
but the actual DT references only the shared AP and APDMA clocks. Their presence
in the clock table is not evidence they must all be enabled. Reconcile this
against the exact stock controller and boot state before native initialization.

These tables are source/DT observations; the native handoff additionally
checks the captured clock and controller state. No physical clock reparenting
has been attempted. APDMA channel addressing alone does not prove cache
coherency or IOMMU routing, and physical touch DMA remains unverified.

The exact stock Image independently corroborates these tables: ``ifr_clks``
records at VAs0xffffff80090523e8 (ID11) and0xffffff8009052a28 (ID38) carry
the same gate shifts and register banks. The I2C top mux record at
0xffffff8009051b68 has offset0xa0, set0xa4, clear0xa8, update0x4,
shift0, width3, gate7 and update bit24; its five parent strings are at
0xffffff80090521f8. Bounded raw records are in the CPU/power evidence package.
