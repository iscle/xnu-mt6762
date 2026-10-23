Opt-in MSDC0 PIO fixture
=======================

The local QEMU fixture exercises the inherited-state native read-only transport
with actual file bytes. It is not a complete MSDC/eMMC implementation and does
not demonstrate stock Linux boot or physical storage access. The fixture is
absent by default. It must be enabled with lab-msdc and an explicit
lab-msdc-image regular file whose length is an integral number of 512-byte
sectors. The image is opened through QEMU's raw BlockBackend without write
permission or image-format probing; shared writers are disallowed. No firmware
partition contents or generated test image belong in the patch series.

The model lives in hw/misc/mt6762_msdc_lab.c with its matching include header.
The board owner wires properties and registration separately. These are local
AI-assisted experiments, not an upstream submission. The two fixture test
suites pass; their exact executable/source hashes, commands, scope and retained
initial failure are in evidence/qemu-msdc-qtest.json. Native guest and physical
storage validation are separate from this report.

Register contract
-----------------

The register layout follows the supplied MT6765 ComboA msdc_reg.h and the exact
stock command/polling/PIO paths recovered by extract_msdc_evidence.py. The
fixture maps 0x11230000–0x1123ffff. It exposes synthetic inherited CFG=0x89
(MODE, PIO, CKSTB), SDC_CFG=0x20000 (eight-bit bus), INTEN=0, no active DMA or
command queue, and crypto software bypass bit 2. It refuses programming of
configuration, clock, reset, DMA, command queue, crypto, TXDATA and FIFO-clear.
It does not model the physical clocks, pads, rails, tuning or IRQ delivery.

The command response arrives after an explicit synthetic 50 microseconds of
QEMU virtual time. Only these exact operations are accepted:

* CMD13 raw 0x8d, argument 0x10000: synthetic RCA1, READY/TRAN R1=0x900.
* CMD8 raw 0x02000888, argument 0 and block count 1: a synthetic 512-byte
  EXT_CSD with user partition selected, CMDQ disabled, BUS_WIDTH=2,
  HS_TIMING=2, revision 8 and CARD_TYPE=0x56. SEC_CNT reflects the actual backing-file sector
  count. These metadata fields are test assumptions, not recovered card data.
* CMD17 raw 0x02000891, sector argument and block count 1: reads the exact
  corresponding 512 bytes from the backing file. Out-of-range requests return
  an R1 error without reading or supplying a payload.

CMDRDY is bit 8; command timeout/CRC are bits 9/10; XFER_COMPL is bit 12;
data timeout/CRC are bits 14/15. INT acknowledgement is W1C and clears only the
requested subset. A pending completion/error cannot be silently overwritten
by another command. FIFO count exposes up to 128 available bytes, RXDATA uses
little-endian 32-bit words, and XFER_COMPL appears only after the final word
has been consumed. FIFO refill is instantaneous in this fixture. The native
transport's deadlines and data-integrity checks must not assume this timing
represents an actual controller.

Fault and evidence boundaries
-----------------------------

The lab-msdc-fault property accepts inherited busy/queue/crypto/stale-IRQ,
command CRC/timeout, data CRC, short payload, missing data completion, stuck
acknowledgement, backend error and wrong-R1 cases. EXT_CSD faults independently
change partition, CMDQ, bus width, timing or capacity. Clearing a model fault
does not reset native ownership/error state. The model never reports a write
as successful, and unsupported commands do not receive fabricated responses.

tests/mt6762/test_lab_msdc.py prepares a small deterministic temporary file,
checks sectors at multiple LBAs byte for byte, verifies its hash remains
unchanged, checks the synthetic EXT_CSD contract and W1C subset behavior, and
exercises the explicit faults and default absence with a paused qtest CPU.
The test does not use the phone dump as its backing image.
test_lab_msdc_inputs.py separately verifies paired-option and image admission,
including missing/nonregular/empty/partial-sector files, concurrent writer-open
rejection, allowed read-only sharing and successful writer-open permission after
the fixture exits. Its qemu-io command is observational ``info``; no write
command runs. The first negative pass found that blk_getlength rounds a
513-byte raw file upward. The model now checks actual stat.st_size before open
and requires the resulting backend length to match. Both suites passed after
that correction, and the initial failure remains recorded.

Native guest tests
must separately prove the real XNU call path and preserve fault/incomplete
outcomes in their evidence. Neither layer proves physical timing, live card
configuration, encryption state, reliable storage or safe card initialization.
