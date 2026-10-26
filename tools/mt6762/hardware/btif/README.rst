MT6765 BTIF PIO and first WMT query
=================================

This original, freestanding implementation supplies the management transport
needed before the separate CONNAC WLAN DMA interface. It is not yet wired to
physical MMIO or kernel startup. It does not start Wi-Fi, scan, associate, or
load firmware. No Apple userspace executable is changed.

``btif_pio.c`` owns bounded byte transfers through an explicitly supplied
register adapter. ``btif_wmt.c`` composes it with the actual mandatory-mode
WMT query parser. Its final state is ``BTIF_WMT_DEFAULT_OPTIONS`` only after
the entire query drains from TX and its exact complete response is accepted.
It does not assert that the common MCU patch is loaded, attest PDA completion,
switch to full STP framing, or publish a network interface.

Register evidence
-----------------

The private audit is retained at
``hardware/hakios-migration-20261026/wifi-native/btif`` in the workspace.
``evidence.json`` here records original Image and function hashes. The recovered
stock ELF's selected bytes were compared with the original Image before
disassembly. The supplied 4.14 BSP is corroborating documentation; the shipped
kernel is 4.19.191, and source equivalence is not assumed.

* Stock ``hal_btif_hw_init`` at Image+0x7b0fb4 sets normal FAKELCR, enables
  handshake, sets thresholds, disables loopback and RX/TX DMA, sets timeout
  auto-reset, disables TX interrupt generation and enables RX generation.
* ``hal_btif_irq_handler`` at Image+0x7b1318 reads 32-bit IIR &0x44, then uses
  byte RBR reads. Its TX half uses LSR bit6 for16 free bytes or bit5 for8,
  then byte THR writes. It does not transfer FIFO data with32-bit accesses.
* The actual ``mtk_btif_info`` descriptor has TX capacity16, RX capacity8,
  TX threshold8 and RX threshold1. DT maps BTIF at0x1100c000 and its GIC
  source atSPI112 (ID144), with APDMA TX/RX at0x11000880/0x11000900.

The new PIO adaptation polls IIR with RX generation enabled but its GIC source
masked. It refuses live DMA, queued bytes or busy TX at initial admission.
Unlike stock init, it never flushes an inherited FIFO. A new command refuses
unsolicited RX both at begin and before its bytes are sent; stale events cannot
satisfy a newly generated query. Receive-only windows remain available.

Ownership and failure contract
------------------------------

The real adapter must first establish exclusive transport ownership, powered
and accessible connectivity, held BTIF/AXI clocks, idle APDMA channels and a
masked GIC source. No boolean in this library proves these facts. ``ready``
must revalidate those conditions from safe always-on state before every batch;
it must not read powered CONSYS registers merely to decide whether they are
accessible. No concurrent owner may change clocks/power or reset the device.

Register callbacks supply the required device-memory ordering. Calls are
serialized and must not run concurrently. No operation changes PLLs, gates,
rails, APDMA, GIC, sleep, wake or reset. Initial setup touches only IER,
FAKELCR, HANDSHAKE, TRI_LVL and DMA_EN, preserving unrelated bits. Writes to
DMA_EN set timeout auto-reset only after both DMA bits were observed clear.

Each step drains at most32 received bytes and writes at most16 bytes. A
monotonic microsecond deadline and one-million-call budget bound every
exchange, including a frozen-clock scenario. ``finish(now_us)`` checks the
deadline again. Failure is sticky; no implicit retry, FIFO flush or recovery
is attempted. The owner must stop the transaction and retain the first error.
Software bounds cannot prevent an inaccessible hardware bus from stalling.

The eight-byte receive FIFO requires working hardware backpressure and prompt
service. Enabling HANDSHAKE is supported by the stock init, but actual peer
flow control and sustained physical receive behavior have not been measured.
The fixture models a peer that pauses at eight bytes; this is an explicit
model assumption, not hardware evidence. An interrupt/DMA receive path may
be needed for later high-throughput firmware/data traffic.

Validation
----------

Run ``python3 tools/mt6762/hardware/btif/test.py`` from the kernel tree.
Tests use a host C compiler with warnings as errors. They exercise byte access
widths, the16/8 TX capacity rules, full FIFOs, partial progress, zero/limited
RX buffers, maximum-frame streaming, ownership/configuration loss, stale RX,
late completion, backwards/frozen clocks and sticky failure. The integrated
query test uses an eight-byte FIFO, delayed polls and a backpressured peer;
corrupt/late replies and undrained TX never establish success.

Both implementation files also compiled freestanding for Cortex-A53. Host
ASan/UBSan linking was unavailable because this environment lacks the GCC
runtime libraries; no sanitizer success is claimed.

Next hardware step is the separately admitted cold-start/patch sequence and a
single default-options query. Complete Wi-Fi still requires calibrated WMT
setup, common firmware loading, CONNAC command/event/data rings, cache/DMA
ownership, scan/join/security handling, and HakiOS station/network integration.
