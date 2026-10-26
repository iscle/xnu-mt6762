Bounded predefined multi-block PIO
==================================

The inherited controller remains in its verified PIO/card/clock/rail/tuning
configuration. This change adds no DMA, clock changes, reset, media writes,
partition switches or interrupt ownership. It addresses an observed throughput
cost: APFS grouped up to128KiB, but the BSD adapter previously decomposed that
into256 independently locked512-byte reads, each CMD13/CMD17/CMD13.

Source and exact-artifact evidence
---------------------------------

The dumped Image SHA256 is
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
Its msdc_command_start range0xffffff8008afb07c..0xffffff8008afb704 hashes to
bc7da45228f50ccba7864dbc7914e2f17cf1d36f1f3bd83ec826f3d025bee1c4,
matching the prior symbolized ELF audit. The raw Image mapping base is
0xffffff8008080000. Its command jump table at0xffffff80090fa0c8 selects:

* CMD17:0xffffff8008afb1a0, dtype1 (0x800).
* CMD18:0xffffff8008afb500, dtype2 (0x1000) for reads; optional auto-command
  bits are separate branches and are not selected by this implementation.
* CMD23:0xffffff8008afb2c8, no data-transfer dtype.

The selected BSP LK platform/common/storage/mmc/msdc.c:749..774 constructs
opcode|response<<7|blocklength<<16 and dtype2 for multi-block reads. Its
msdc_pio_bread at1697..1742 demonstrates a variable block count and PIO length.
The explicit mmc_set_blk_count helper in mmc_core.c:2017 is CTP-gated: it is
reference code, not proof that the dumped LK executed that branch. The selected
kernel-4.14/drivers/mmc/core/block.c:2395..2423 describes predefined transfers
and issues CMD23 with block count;3987..3992 enables it for MMC versions3+.
The existing native admission requires EXT_CSD, compatible HS timing and modern
card capabilities. Actual success on this card remains a physical test boundary.

Protocol and publication
------------------------

A single sector keeps the previous CMD13/CMD17/CMD13 path. A batch of2..256
sectors uses exactly CMD13(0x8d), CMD23(0x97,count),
CMD18(0x02001092,start LBA), CMD13. CMD23's upper reliable-write/data-tag/packed
flags remain zero. SDC_BLK_NUM is programmed to the same bounded count and its
readback checked. There is no autoCMD12/23 and no open-ended read command.

The card must remain READY_FOR_DATA/TRAN after CMD23, and return READY/TRAN
with empty FIFO, no pending interrupts, quiescent DMA/CQE and unchanged owned
controller/clock state after completion. Exactly count*512 bytes and hardware
data-completion status are required. Errors win over simultaneous completion.
Progress deadlines and finite polling counts remain active, including frozen
and backward clocks; progress never turns a hardware CRC into success.

Any ambiguous partial operation latches the existing terminal fault. In normal
Linux an erroneous predefined transfer may require CMD12 recovery. This narrow
consumer deliberately does not attempt that recovery, reset or retry; it stops
using the controller. An unsupported CMD23 does not silently fall back.

The BSD adapter holds one transport mutex across a strategy request. A single
128KiB heap bounce is allocated before publication, rather than on the kernel
stack or per request. Output is copied only after all transfer and post-state
checks pass. Failed strategy requests retain their full residual and unchanged
output. Near-EOF success publishes only the valid prefix and leaves the exact
remaining residual; negative, unaligned and out-of-slice requests are rejected.
Unaligned character reads retain their one-sector scratch and release the mutex
before uiomove, whose faults can recursively need filesystem reads.

At128KiB this changes768 commands to4 and1792 admission calls to8, but leaves
32768FIFO word reads and their existing MMIO barriers. This is not DMA throughput
and does not imply a particular physical speedup.

Measurement and remaining delay
-------------------------------

``MT6762_MSDC_PERF`` retains sector/read-time/admission statistics and adds
batches, singles, commands, cmd13/cmd17/cmd18/cmd23, command_us and data_us.
Command counts include initial admission commands. Command timing runs from
issuing a command to the first completion/error status; data timing runs from
successful data-command response to completion acknowledgement (or terminal
failure). They include descheduling and are not CPU-utilization measurements.
Existing read_us measures inside the serialized callback, excluding time waiting
to acquire its BSD mutex. Existing full_us measures full ownership observations.

Before this change, capture36's first270s storage interval spent259.143s inside
read_sector; capture37 spent260.312s. Final physical per-sector times average
319.4us and319.6us respectively, about1.53MiB/s. The eight-core QEMU56 run averaged
290.9us/sector (~1.68MiB/s), despite skipping physical pad/rail admission. Full
physical observations consume about16% of read time; deleting those checks alone
cannot account for most of the cost. These are different runs, not controlled
before/after benchmarks. Storage-relative wall intervals must not be equated
with launchd's timestamp origin.

Capture37's eight physical cores reached window-server-ready at279.715s,
compared with278.206s in two-core capture36. Capture37 still had no donor-unlock
marker by its retained end (~13minutes), while QEMU56's600s final frame showed
a home screen. Cold PIO cost is concrete, but a later Apple service/main-thread
delay remains a separate possibility. ``kern.apfs_stats`` already reports
metadata cache hits/misses, read/pagein bytes, decompression and per-process
lock waits; a bounded read-only sampler can distinguish these without guessing
cache amplification. No such counter sample is asserted by the old captures.

Validation
----------

``sh tools/mt6762/hardware/storage/test.sh`` passes existing single-sector,
clock, admission and poll-delay cases plus:

* Actual bulk protocol at2/32/256sectors; exact command sequence, payload/canaries,
  count/capacity/overlap rejection and unchanged failure output.
* Command/data/ownership/ack/post-state faults, simultaneous error+completion,
  missing data/completion, normal/frozen/backward clocks and terminal no-retry.
* Extracted actual BSD request/lock code: one callback per128KiB, correct slice
  offset, partial EOF residual, full failed residual, no writes and no transport
  calls for invalid requests.
* Extracted actual BSD publication and cleanup: all six registration failure
  points remove exactly the previously created nodes/registrations, clear the
  callback and capacities, leave ready false, and reject subsequent attempts.
  Successful whole-disk/slice publication and malformed extent admission are
  also exercised. This caught coverage missing from the first strategy-only
  harness; review found and corrected the stale sector_read cleanup name.

These are host protocol/control-flow tests. Genuine kernel build, updated QEMU
model and physical correctness/performance are separate acceptance steps.
