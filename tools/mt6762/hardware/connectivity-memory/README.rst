Connectivity memory admission and reservation proposal
=====================================================

This freestanding C core validates an executing boot's LK/FDT memory ownership
snapshot and proposes two ranges. It performs no allocation, memory mapping,
RAM access, zeroing, cache maintenance, MMIO, SMC, power or DMA operation.
Default-off admission requires ``cm_request.enabled == 1``. Success is NOT a
hardware grant or a committed reservation. There is no kernel/loader integration.

Evidence and supported format
-----------------------------

The supplied LK ``lib/mblock/mblock_v2.h`` describes a native ARM structure;
capture40's ``/memory/mblock_info`` contains exactly that 22,552-byte layout.
It is little endian, unlike FDT cells. Offsets are decoded bytewise, never by
casting possibly unaligned captured data to a native C structure:

* Free count at0; 128 slots at8, stride24: start64, size64, rank32, padding.
* Magic99999999 at3080, version2 at3084, reserved count at3088.
* 128 reserved slots at3096, stride152: start64, size64, mapping32,
  NUL-terminated name[128], padding.

Counts are bounded by128; ranks by the LK format's four-rank maximum (not by
FDT bank count). Mapping must be0/1, but neither value grants access. Padding
and unused slots are deliberately ignored: they are not semantic fields.
Selected reserved names must be nonempty, terminated printable ASCII. One
zero-sized free slot is legitimate in capture40; its address must still fall
within/on the end of a bank. Nonempty ranges must be overflow-free, each lie
inside a supplied bank, and be pairwise disjoint across both ownership sets.
Their sum must exactly cover the nonoverlapping FDT banks. Banks and totals
are parameterized; the core does not hardcode a6GiB result.

The existing unmodified physical FDT parser validates the entire container
first. The second pass requires one mblock_info property on a root memory or
memory@ node. Arbitrarily named device_type=memory nodes remain unsupported
for locating this property and fail closed. The two exact reserved child
names, compatible strings, no-map markers, sizes4MiB/3MiB and16MiB alignment
must match. Disabled targets, preassigned reg, reusable/default DMA ownership,
missing or duplicate significant fields are rejected. Bounds come from each
node's actual alloc-ranges/alloc-range, not a compiled address suggestion.
Every other dynamic owner's whole allocation interval stays excluded, even
when equal to a target's interval. Fixed memreserve/reg must be contained in
one LK reserved entry; spanning several adjacent entries conservatively fails.

The current cells ``0 40000000 0 80000000`` describe [40000000,c0000000).
The last pair is a SIZE, not an end address. Capture40 has18 free slots and28
reserved entries, accounting for all6GiB. Its other dynamic owners conservatively
exclude [40000000,a0000000) and [c0000000,d0000000). The eligible LK free extent
[a0000000,b3330000) yields CONSYS[a0000000,a0400000) and Wi-Fi[a1000000,a1300000).
These addresses are test results, never defaults. Captured raw FDT/table bytes
remain private and are not part of this source package.

Integration contract
--------------------

``cm_parse_mblock`` independently validates the table against caller-supplied,
already validated banks. ``cm_plan`` takes the current immutable FDT and a
caller-owned workspace (7,080 bytes on the64-bit host ABI; do not place it on a small kernel
stack), an output ledger, and required live source-image, managed-kernel and
loader/stack/scratch ranges. Each required range must be nonempty and contained
in one actual bank. Include all other live allocations in ``additional``;
unknown ownership is not inferred free. Overlapping exclusions are permitted.
FDT physical address/length and reported framebuffer are excluded automatically.
Inputs, workspace and output must not alias, and no concurrent writer may
change the FDT during either validation pass.

The search examines at most256*256 aligned pairs below4GiB, using backtracking
so an early CONSYS choice cannot consume Wi-Fi's only valid location. Both
ranges must independently fit inside one target interval and one LK-free
entry. All real LK reservations are excluded by that disjoint ownership test.
Errors zero the output ledger. A successful proposal records version, owner
order, exact ranges, table counts/totals, FDT location and caller's fresh boot
identifier. The identifier is provenance, not cryptographic authentication;
a saved capture plus a made-up identifier cannot authorize physical use.

Future integration must run this against the executing boot's live FDT,
atomically commit both ranges to a single owned reservation ledger before any
consumer can allocate/use them, bind that ledger to the same-image handoff,
and preserve it for the full peripheral lifetime. It must not allocate from
an earlier proposal after allocations change: pass the changed reservations
and rerun. A repeat call with identical input is a repeat proposal, not an
idempotent allocator. No old-boot ownership survives implicitly. Hashes in the
host evidence establish artifact identity only, not freshness or quiescence.
Any future expansion of general XNU RAM must consume the committed ledger.
The current general FDT parser's conservative allocation exclusions remain
unchanged, keeping both proposed ranges outside its managed window.

Unmanaged mapping and remaining gates
------------------------------------

The selected ranges are below the current managed [d0000000,1bfe00000) window.
They have no VM-page allocation ownership. XNU's io_map/pmap_map can map
unmanaged physical ranges, but integration must carry explicit PA and VA;
do not use phystokv/ml_static_ptovirt or kvtophys_nofail for these buffers.
Do not broaden the platform's register-mapping allowlist to cover arbitrary RAM.
A separate exact-range reservation capability is required. ml_io_map selects
Device memory; ml_io_map_wcomb selects normal noncacheable memory. The correct
cache/shareability policy for each firmware/descriptor/data use must be
established separately, with no conflicting cached aliases and no assumption
that peripheral DMA is coherent. The precompiled userspace16KiB VM and existing
4KiB hardware PTE arrangement are untouched.

CONN reset/power state, bus-master quiescence, EMI/secure-region permission,
firmware identity/download, physical remap registers, and firmware's view of
addresses are all independent outstanding prerequisites. The CONN remap's
16MiB granularity explains the allocation alignment; it does not authorize
programming it. No SMC or secure EMI operation is implemented. Capture40's
free table is evidence of LK allocation ownership, not proof that an unknown
firmware bus master cannot access the range. Reset/DA retention is unproved.

Validation
----------

Run from any working directory::

  python3 /path/to/connectivity-memory/test_conn_memory.py -v

This compiles the actual core and unchanged FDT parser with C11, optimization,
-Wall -Wextra -Werror and -ffreestanding. The optional private real-artifact
check is enabled by ``CM_CAPTURE40=/path/to/capture40/runtime.dtb`` and requires
its exact recorded SHA256. Synthetic tests remain self-contained and cover
malformed/truncated tables/FDT, overflow, count/rank/name/mapping errors,
coverage/overlap, changed and duplicate owners, fixed ownership inconsistency,
other dynamic exclusions, live exclusions, no-space and pair backtracking.
The tests make no device accesses and write no actual physical RAM.
