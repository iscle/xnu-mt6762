Retained display validation snapshot
====================================

Image7 reaches diagnostic PID1 on the phone but its kernel log has no Video
framebuffer. Image8 adds a512-byte, build-bound RAM record at0x40084100 beside
the existing phase record. Both fit below the reserved download-agent heap
start0x40090000. The record is initialized in the delivered Image, outside BSS,
and carries the same random build identity as the phase trace. No persistent
log or display-register write is added.

The exact console validator records the first rejected stage: framebuffer tag,
bounds, independent reservation, power, gates, sources or scanout. It stores
the candidate allocation, power-status copies, display power control, clock
gates and source mask. Only after valid power and gates does it read OVL/RDMA/
DSI. When source bits identify the four supported hardware layers, it captures
each enabled layer, including a rejected multi-layer state. Admission still
requires the previous single-layer, exact-format/timing predicates on both
passes. The snapshot does not grant native peripheral ownership.

The last attempted pass has an explicit read-valid mask. Unread fields may
contain earlier-pass data and the decoder omits them. A state/inverse commit
with barriers distinguishes completed validation from a torn or incomplete
record. Reset retention and cache completeness still require separate evidence;
the decoder never claims either from a syntactically valid record alone.

Why capture every enabled layer
------------------------------

Static examination of the supplied LK finds main layer0 and boot-menu layer1
enabled during initialization, with conditional round-corner layers2/3
(0x48000e26 through0x48000fb2). This can conflict with the validator's one-hot
source requirement, but does not establish the actual final handoff state.
LK initially selects framebuffer base plus two aligned0x144000 frames. Its
final boot path calls0x480012a0 from0x4801b5c8 and attempts to copy back and
normalize layer0 to the tag base. The retained tag alone cannot identify the
actual scanned buffer. These are static observations, not runtime measurements.

The tag allocation0x7ef90000/0x470000,1536-byte pitch and BGRA8888 format match
the inspected binary. The supplied BSP source differs in initial buffer offset,
so this probe uses actual register readback to resolve that uncertainty.

Validation
----------

test_display_probe.py compiles the same C validator used by the loader. It
checks both passes, refusal before powered-off/gated block reads, missing
reservation, bad bounds, source masks, address drift and all four layer indices.
The produced C wire record is decoded by display_record.py; malformed identity,
commit, mask and pass data are rejected. Existing guarded renderer tests remain.

The exact delivered normal-boot Image8 passes the59-test physical host suite,
the serial PID1/205-case QEMU boot, static-memory refusal, and simulated display
admission. Its QEMU framebuffer was visually reviewed and shows both successful
205-case rounds and MT6762_IIG_PROBE_DONE. These are software checks; the next
phone capture must identify the real display failure before changing admission.

Capture9 and Image9 menu-console support
---------------------------------------

Capture9 measured sources3: full-screen BGRA layer0 at0x7ef90000 and layer1
at0x7f0d4000, both inside the original0x470000 reservation. CON was0x21ff,
full pitch1536, and offsets/clips/extended layers were zero. This proves the
single-layer predicate rejected the actual handoff. XNU again completed both
205-case diagnostic rounds, with no physical Video framebuffer selected.

A second mismatch was DSI_PSCTRL0x2c030480. The MT6765 LK DSI_PS_Control maps
API enum RGB888=2 to hardware selector5-2=3. Exact stock-kernel instructions at
0xffffff800876d8ac through0xffffff800876d8b8 corroborate that remap. The shared
validator now expects selector3 and1152 bytes/line with swaps clear. It also
checks the full pitch word, rejecting alternate blend controls in its upper
bits. These corrections do not program the display hardware.

Image9 accepts the measured two-layer menu profile only when both complete
layers match, their buffers fit the original independent reservation, and
both passes agree on the selected buffer. The upper menu buffer is used for
text. Version2 of the512-byte record adds DATAPATH_CON and SBCH at offsets432
and436, with read-mask bit32. Admission rejects GPU/PQ/bypass/interlace/wide-
gamut/background-routing modes and any SBCH caching. Only SMI IDs, output
rounding disable, GCLAST and output clamp are allowed in DATAPATH_CON. Those
two register values were not captured by Image8; Image9 measures them live.
The decoder remains compatible with historical version1 records.

The loader clears only the validated visible buffer to an opaque background.
Kernel29 makes32-bit MT6762 console foreground/background colors opaque as
well, including cells erased during scrolling. The original Apple userspace
binaries are unchanged. Native display, brightness, DMA and power ownership
are still separate unfinished work.

All59 physical host tests and the shared display-core test pass. The delivered
Image9 reaches serial PID1 and the complete visible diagnostic under both
single-layer and explicitly selected two-layer QEMU fixtures. Saved framebuffers
match SHA25669e0d80ce1f1250d571197a0702ab7de2ce48ddd966b9aa548f14ee3135c6bd0;
every visible pixel has alpha255. An initially incomplete image preview was
not reproduced: the saved bytes, original-resolution image and separate
retained-log probe all show the completed diagnostic. No physical readiness
claim follows from that emulator result. See trace-build9-evidence.json.
