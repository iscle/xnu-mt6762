Bounded SoC WMT / BTIF management protocol
=========================================

``wmt_protocol.c`` is original, freestanding C99 source. It performs no register
access, firmware transfer, allocation, thread creation or transport operation.
``cw_init(s, 0)`` is disabled. The implemented result is **STP options verified**,
not Wi-Fi readiness, successful firmware boot, scan capability or hardware
ownership. Its only commands are the exact shipped SoC query / set-STP options.

Evidence and ordering
---------------------

``protocol-evidence.json`` binds the dumped ``wmt_drv.ko`` hash, section-relative
symbols and relocations, and the supplied BSP source hashes. The ELF contains
multiple similarly named tables for different chips. The SoC function
``_wmt_soc_mode_ctrl`` selects .data+0x2dc8 (SET) and .data+0x2df0 (QUERY), whose
relocations select .data+0x2e27 and .data+0x2e36 respectively. This establishes
the DB option byte, rather than DF used in several other tables.

The supplied BSP paths below are relative to
``vendor/mediatek/kernel_modules/connectivity/common/common_main``:

* ``core/wmt_core.c:840-873``: reset STP state; choose BTIF mandatory mode,
  enable it. This is a host software framing choice, not a BTIF power sequence.
* ``core/wmt_ic_soc.c:1130-1175``: query default options, SET, reinitialize host
  full framing, wait 10 ms, then query and match configured options. The exact
  dumped function confirms this table chain and ``osal_sleep_ms(10)``.
* ``platform/mt6765.c:162-173`` and ``include/wmt_plat.h:261-278``: PDA patch
  profile. The shipped ``mtk_wcn_emi_addr_info`` .data+0x448 has u32 +0x24 = 1.
* ``core/wmt_ic_soc.c:1224-1230,1351-1358``: non-PDA chips switch before patch
  download; this PDA profile switches **after** patch download/reset. A cold
  transport probe may query the default options, but must not jump directly to
  full framing as a substitute for the missing PDA download implementation.
* ``core/stp_core.c:1126-1224,1746-1911,2035-2230,2350-2387``: mandatory and
  full headers, streaming receive, checksum, CRC, transport selection.
* ``linux/osal.c:59-92,323-336``: reflected CRC16 polynomial 0xa001, initial
  zero, no final XOR. The shipped 512-byte table agrees; ASCII ``123456789``
  gives 0xbb3d, query bytes ``01 04 01 00 04`` give 0xf36c (wire ``6c f3``).

Wire subset
-----------

WMT is type/opcode/u16-LE body length followed by body. Commands use type 1;
events type 2; the first event body byte is status, which must be zero here.
Exact complete event bytes are matched, including options and subopcode.
No variable-length placeholder or generic success event is accepted.

BTIF mandatory framing is ``80 / channel+length-high / length-low / 00``,
payload, two zero trailer bytes. It has no CRC protection; strict zero checks
cannot substitute for a CRC. BTIF has no SDIO four-byte aggregation padding.
This management subset accepts channel 4 only and rejects diagnostic/coredump
channels rather than pretending those messages are WMT events.

Full framing is ``80|seq<<3|ack / channel+length-high / length-low / sum8``;
payload is followed by little-endian CRC16. Zero-length ACK packets are four
bytes with channel zero and no CRC. Sequence and ACK are modulo eight;
initial receive sequence is zero and initial transmitted ACK is seven.
The core has one outstanding command and accepts its prior ACK or current ACK;
regression after acknowledgement, wrong sequence, NAK and resynchronization
requests are terminal. Up to two optional 0x55 delimiter bytes are accepted
before each full packet. There are no automatic retries or recovery guesses.
This is deliberately narrower than stock's seven-packet retry window.

Integration contract
--------------------

State belongs to one serialized caller. Do not alias output/input buffers with
its internal state. The adapter must independently establish power, clocks,
BTIF ownership/configuration and a monotonic microsecond clock. APIs are:

1. ``cw_init(s, 1)``, then ``cw_command(...CW_QUERY_DEFAULT...)``. Send exactly
   the returned bytes and require the transport's entire write to succeed.
2. Feed bounded received spans through ``cw_feed``; call ``cw_poll`` while
   waiting. A matched default event produces ``CW_DEFAULT_VERIFIED``.
3. Before SET, explicitly call ``cw_attest_pda_patch_reset``. This call records
   a caller attestation, **not independently verified evidence**. It qualifies
   only after the separate, correctly admitted PDA transfer completed every
   required segment, matched firmware acceptance responses, and matched the
   firmware reset response. Validating files, seeing default options, or
   returning success from an unimplemented downloader does not qualify.
4. ``CW_SET_FULL`` must match its exact event. Reconfigure/reset the host STP
   framing state, then call ``cw_enter_full`` at least 10 ms after the event.
   No hardware configuration is performed by that call.
5. Send ``CW_QUERY_FULL``. The result becomes ``CW_OPTIONS_VERIFIED`` only after
   exact event matching and ACK of the outstanding command. Drain
   ``cw_take_ack`` and require the returned four bytes to be fully transmitted.
   Taking bytes from this API does **not** prove they reached the device.

Every command has an explicit 1 ms..10 s deadline anchored at output generation
(before transmission, so a slow write cannot extend it). Backwards clocks,
expiry and one million pending polling/feed calls are terminal; this also bounds
frozen-clock loops. The SET deadline includes mode switching. A timeout below
10 ms cannot accommodate that switch. No deadline can be extended by partial
packets, ACKs or bytes arriving continuously. Clock must keep running while
waiting. Calls process at most 65536 input bytes; STP payload is at most 2048
(less than 2000 in mandatory mode) and WMT message at most 64. An error is sticky
and all further I/O must stop. Transport failures likewise require discarding
the session; do not interpret an earlier matched event as overall success.

The transport adapter is responsible for scheduling ACK transmission promptly,
logging exact terminal errors, and discarding the session on partial writes or
hardware errors. No callback or state in this file authorizes CONN MMIO/DMA.

Tests and current boundary
--------------------------

Run ``python3 -m unittest discover -s tools/mt6762/hardware/connectivity -p
 'test_*.py'`` from the kernel tree. The 26 protocol tests compile with C99,
``-Wall -Wextra -Werror`` and cover exact commands, every mandatory split,
bytewise full input, split WMT across STP packets, coalesced ACK/event, delayed
ACK, checksum/CRC/status/options/channel/sequence rejection, PDA prerequisite,
mode delay, capacity/truncation and clock/deadline/poll-budget bounds.
The additional 20 artifact/passive-state tests remain passing. The initial test
fixture had an incorrect handwritten query CRC; extracting the shipped table
confirmed 0xf36c, and the fixture was corrected. No hardware test occurred.

Still missing before firmware boot or scan: physical power/rail/clock admission,
BTIF adapter integration, exact PDA destination/remap/EMI ownership and complete
transfer/reset implementation, live chip/ECO/ADIE validation, calibrated WMT
setup, CONNAC firmware download and command/event/data rings, DMA/cache handling,
regulatory/calibration admission, and HakiOS station/network integration.
The current commands do not enable a radio, issue scan requests or invent
calibration, ADIE identity, or a region.
