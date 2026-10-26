Physical MSDC read timeout
==========================

Capture34, Image40/kernel54, terminated storage at37.656020 seconds with
CMD17, LBA14154566, phase2, bytes0, IRQ0 and stalled_us20000. The protocol
accepted the command response but received no first64-byte FIFO chunk before
its software deadline. It did not report a hardware data timeout or CRC error.
This establishes a20ms software cutoff, not the eventual cause of the delay.
The existing expiry re-sample already checks fresh IRQ/FIFO state before
rejecting an apparently unfinished transfer.

The physical builder now supplies ``msdc-timeout-us=1000000`` through the
existing handoff. The protocol already accepts this value and rejects values
above it. No kernel header, controller configuration, DMA mode, card command,
retry, reset or terminal-error policy changes are needed. The next physical
trial can use the same kernel54 and two CPUs, isolating this policy change.
It is an experiment with a longer bounded wait, not a claim that the failing
sector is proven readable or that the underlying fault has been repaired.

Controller and stock evidence
-----------------------------

Both capture34 passive passes read MSDC_CFG0x02200199 at0x11230000 and
SDC_CFG0x09020000 at0x11230030. The former encodes CKMOD2 (DDR); the latter
encodes DTOC9 in bits31:24. The admitted clock was47,999,984Hz. The exact stock
``msdc_set_timeout`` function and matching BSP encode a requested read timeout
in2^20 card-clock units, multiply the count by2 in DDR, then subtract1 and
saturate to255. Decoding that programming convention gives the nominal value::

    ((DTOC + 1) * 1048576) / (card_clock_hz * 2)
    = 109226.7030755677 microseconds

This is the duration implied by the captured configuration and the stock
driver's formula. It is not a measured expiry time or proof that an arbitrary
stalled clock/controller will assert DATTMO. The20ms software limit was below
this approximately109ms hardware setting. The1s policy allows hardware errors
to be observed first when that inherited mechanism operates as programmed.

Exact original stock ELF SHA256:
643474799f7c300f2d3c7f5130f697ee359929f13db0750f4dd7b9d648af14fc.

* ``msdc_set_timeout`` at0xffffff8008afaa64..0xffffff8008afab80:
  CKMOD extraction at0xffffff8008afaab8; rounded2^20 division and DDR doubling
  at0xffffff8008afaac0..aad0; subtract1/saturation at0xffffff8008afaad4..aae4;
  SDC_CFG field insertion/store at0xffffff8008afaaf8..aafc.
* ``msdc_pio_read`` at0xffffff8008afc5d0..0xffffff8008afcc60:
  xfer_size>511 selects0xffffff8008afc650, adding0x4e2=1250 jiffies to the
  start tick. The original embedded kernel configuration has CONFIG_HZ=250,
  so the stock512-byte PIO software deadline is5seconds. Hardware errors are
  checked independently at0xffffff8008afc6bc..6c0.
* BSP ``kernel-4.14/drivers/mmc/host/mediatek/ComboA/sd.c:723`` implements the
  same DTOC arithmetic. Its PIO read at2155 selects DAT_TIMEOUT for512bytes;
  ``mtk_sd.h:619`` defines CMD_TIMEOUT=HZ/10*5 and DAT_TIMEOUT=HZ*5.

The1s value is deliberately within the existing native interface cap. It is
shorter than the stock5s PIO deadline and is not asserted to cover every valid
eMMC latency. It also changes the shared command-response limit from20ms to1s;
the stock command limit is500ms. Splitting command and data limits would be a
separate protocol change and is unnecessary for this isolated trial.

Avoid an unsupported generic eMMC worst-case claim. Exact stock
``mmc_set_data_timeout`` at0xffffff8008ade114..e254 and BSP
``kernel-4.14/drivers/mmc/core/core.c:1768`` start MMC read timeouts from10times
the card's CSD TAAC time/cycles. A long-read quirk can select600ms. The100ms SD
limit, SPI minimum and comments about long write-busy times are different
conditions and do not establish this card's read limit. This audit has not
decoded a current CSD/quirk instance or measured this card's maximum read
latency. EXT_CSD revision8 alone supplies neither fact.

Bounds and unchanged failures
-----------------------------

``mt6762_msdc_protocol.h`` uses the handoff limit for each command response
and each no-progress FIFO/completion interval. Each64-byte chunk restarts the
data interval, with at most eight chunks. Thus1s is not a whole-sector or
whole-request deadline. There can be nine data wait intervals including
completion, plus three command-response waits. Fresh ready data/completion
can still be accepted after a scheduling gap; the deadline is not a real-time
CPU execution guarantee. The independent poll-count bound still terminates
if the supplied clock freezes, and backward time fails immediately.

Hardware DATTMO/DATCRCERR take precedence over data and completion. An error
still latches terminal storage failure, exposes no staged bytes, and admits no
subsequent controller access. No timeout retry is introduced. A1s bound
therefore cannot hide a reported controller fault, but it may postpone failure
when the controller remains silent. Capture34 alone cannot distinguish a
legitimate long first-data latency from a permanent stall or another defect.

Host regression
---------------

``test_msdc_pio.c`` executes the actual unchanged production protocol with the
captured DDR configuration and a FIFO model that initially has no data:

* First FIFO at25ms and100ms:20ms fails with phase2/bytes0/IRQ0;1s succeeds
  with the expected512bytes and the existing CMD13/CMD17/CMD13 sequence.
* DATTMO, DATCRCERR and both bits at25ms remain terminal even with simultaneous
  FIFO availability. Output stays unchanged; a following call performs no MMIO.
* Permanently absent FIFO stops at1s; a frozen clock stops at the independent
  bounded poll count. Neither emits a retry/reset or publishes partial data.
* Zero or1,000,001us handoff values fail before any MMIO.

``sh tools/mt6762/hardware/storage/test.sh`` passes the new regression and the
existing command/data, scheduling-gap, ownership, clock, admission and delay
tests. This models the policy distinction; it is not a physical card-latency
test. Artifact/source hashes and exact stock spans are recorded in
``data-timeout-evidence.json``. No phone command or kernel build was run by
this audit.
