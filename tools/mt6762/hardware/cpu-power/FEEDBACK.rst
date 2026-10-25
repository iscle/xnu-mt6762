Exact stock SSPM DVFS feedback boundary
======================================

This is an offline AP-side audit of the retained phone Image and symbolized
stock ELF, pinned by SHA-256 in ``evidence/feedback-evidence.json``. The BSP
is reference source, not assumed byte-identical. REA's native provider was
unavailable in this session; installed Capstone, pyelftools and Unicorn provide
the bounded fallback. No device command, clock write, vote or new native
readiness flag is introduced.

Request is not completion
-------------------------

``cpuhvfs_set_cluster_load_freq`` at 0xffffff800867b4f8 increments a global
counter, wraps 255 to 1, combines ``index | counter << 4``, writes the domain's
CSRAM word at 0x3a4 + 4*domain, issues DSB SY and returns zero. It does not wait
for the counter to be echoed, a current-index change, a mailbox reply or a
voltage transition. Its return means the AP submitted a vote. Domain remapping
and table selection remain subject to the existing platform audit.

The exact ``cpuhvfs_get_cur_dvfs_freq_idx`` at 0xffffff800867b230 is a raw load
from CSRAM+0x354+4*domain. ``cpuhvfs_get_volt`` at 0xffffff800867b304 reads
CSRAM+0x32c+4*buck. Neither snapshot contains a checked vote sequence or age.
The voltage getter does not establish units, a physical rail measurement or
correlation to a particular log entry.

Notification record
-------------------

The CPU receive descriptor 0x2081a selects mailbox2, slot3, four words. The
exact ``Ripi_cpu_dvfs_thread`` copies only the first two words as ring start
and exclusive end offsets. Its ring begins at CSRAM+0x3d0 and wraps at 0xf88:
150 entries of five 32-bit words, not 150 entries containing a vote counter.

Each entry contains a little-endian 64-bit timestamp and three domain words.
The executed original decoder extracts only OPP index [15:12], limit [7:4]
and base [11:8]. The reference header names the other fields turbo [1:0],
cluster-enabled [3:2], scheduler index [20:16], WFI index [24:21] and padding
[31:25]. Those names are BSP evidence; there is no producer-side proof that
ignored bits echo a request sequence. No voltage is decoded from the ring.
Timestamps are concatenated without unit conversion or AP-clock correlation.

For multiple records the AP computes a time-weighted frequency from the
previous record's OPP over each timestamp interval, chooses a table index,
and clamps it using the last record's limits. Its Linux frequency transition
notification therefore is not necessarily the last logged OPP. The callback's
``transition_end(..., 0)`` is an AP policy notification, not a firmware ACK.

Loss and bounds matter
----------------------

The exact receive wait at 0xffffff800880a40c drains repeated completions when
an action lock exists. The exact ISR callback at 0xffffff800880a104 skips both
copy and completion when that lock's trylock fails. Unicorn executes both
branches with modeled OS locks/completions; this corroborates the BSP's drop
and coalescing behavior. One callback cannot be counted as one completed vote.
The hardware interrupt wrapper acknowledges the observed mailbox status before
calling that callback; this is not a request-sequence acknowledgement either.

Unlike the supplied BSP's MAX_LOG_FETCH condition, this Image's read loop at
0xffffff800867a808..a884 loops until the end offset, then clamps the count to
40. The decoders guard out-of-range indices by warning and using entry zero;
this does not bound the ring traversal or make malformed end offsets safe.
Do not port that loop literally. Validate both offsets inside [0x3d0,0xf88),
20-byte alignment relative to 0x3d0, modulo distance and an explicit record
limit before reading. Treat start==end as no observable records, with full-wrap
ambiguity, rather than asserting no transitions occurred. A bounded observer
must reject or report truncation, non-increasing timestamps and overwritten or
inconsistent snapshots; it must not silently certify freshness from them.

Implementable boundary
----------------------

A read-only observer can decode a bounded, consistently captured notification
interval; report the last observed OPP, limits, raw timestamp and separately
sampled current index; and expose dropped/truncated/invalid intervals. A later
owned vote implementation can report ``submitted`` and separately
``target observed/converged`` when a new valid interval and independent stable
PLL/divider/rail/table checks agree. It cannot call that a sequence-matched
completion on this AP evidence. Repeated targets, delayed/coalesced callbacks,
ring overwrite, counter wrap and autonomous PPM/EEM changes defeat that claim.
Double-reading a ring is not proof against a producer wrapping and replacing
identical data. No timestamp units, maximum producer delay or rollback protocol
has been recovered here.

Before active control, a physical producer must transfer exclusive scheduler,
PPM, EEM, hotplug/suspend, CSRAM and CPU notification ownership; identify the
active SSPM firmware/ABI and initialized controller; preserve its actual shared
DRAM and calibrated PVT/EEM state; and establish CPU/CCI/rail constraints and
a bounded failure response. INIT_PTBL/INIT_STA are not safe handoff probes:
stock initialization creates tables, clears shared repository data and sends
initialization commands. PLATFORM liveness proves none of these conditions.
The mailbox0-only native driver does not own mailbox2's notification path.
``dvfs_control_ready`` must remain false pending this missing contract. No
physical producer or native ring/transition controller is supplied by this audit.

Reproduction
------------

Run with existing Python capstone, pyelftools and unicorn modules::

  python3 audit_feedback.py --image /path/to/Image --elf /path/to/stock.elf \
    --bsp /path/to/workspace --output /private/output

The script rejects other Image/ELF hashes, checks symbol addresses, hashes
bounded code spans and BSP files, emits bounded disassembly, and executes six
cases: all 32 cluster-bit positions plus baseline, three raw current-index
reads, receive wait with/without coalescing, and successful/dropped notification
copy. OS scheduling/locking, RAM and copy callbacks are explicitly modeled;
no SSPM producer, peripheral timing, live memory or hardware is emulated.
The generated evidence contains hashes, addresses and synthetic vectors, not
private retained logs or firmware bytes. Complete bounded disassembly stays
in the requested private output directory.
