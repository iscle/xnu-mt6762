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
