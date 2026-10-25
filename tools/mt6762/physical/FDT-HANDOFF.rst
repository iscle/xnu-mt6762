Bounded physical FDT handoff
===========================

``fdt_handoff.c`` is freestanding C with no libc calls or original kernel
headers. It reads only the accessible buffer supplied by the loader. A malformed
or unsupported tree returns a negative enum and zeroes the output structure.
No device registers are accessed and no display/pin/native-I/O authority is
created by parsing metadata.

The parser accepts FDT version17 with total size at most2MiB, independently
checks structure/string/reservation bounds and overlap, checks terminated node
and property names, balances at most64 nested nodes, and requires root address
and size cells2/2. Memory ranges must be nonzero, non-overflowing and disjoint.
There are at most16 memory banks and64 reservation exclusions. Root compatibility
is matched exactly against mediatek,MT6765 or mediatek,MT6762; the loader must
require ``board_compatible`` before using this board's boot path.

The memreserve header and reserved-memory child reg ranges are collected.
When a reserved-memory child has no reg, the complete explicitly bounded
alloc-ranges or alloc-range intervals are excluded conservatively. No allocation
address is guessed from size/alignment. Missing bounds, unknown cell widths,
translated reserved-memory ranges and ambiguous declarations are rejected.
One exact LK-generated inert placeholder is accepted: a direct child named
``zone-movable-cma-memory`` with no properties or children. LK's
``memory_lowpwer_fixup`` creates it before checking for the source allocation
node and can exit leaving it empty. Without reg or size it declares no
reservation, matching the supplied Linux reserved-memory scan. Any property,
child, unit-address suffix or different name prevents this exception; populated
nodes still require ordinary valid reg/alloc bounds. No actual range is dropped.
Overlapping reservation exclusions are valid and act as a union. Adjacent RAM
banks are treated separately; this can conservatively reject an otherwise
contiguous allocation across a bank boundary.

``mtk_fdt_select_window`` searches only parsed RAM for a512MiB window aligned2MiB,
starting at or above0x80000000 and ending at or below4GiB. It excludes reservations,
the actual physical FDT buffer, recognized framebuffer memory, and every caller
exclusion. The caller must supply the live loader, stack, source payload and
scratch allocations; none can be inferred safely from a static dump. Failure
returns no-window and base0. The FDT address is a required argument, not inferred
from its contents.

The optional /chosen/framebuffer reg/width/height/stride properties and MediaTek
/chosen/atag,videolfb tag are informational. The latter is decoded using the
verified LK layout: little-endian64-bit base,32-bit found/fps/VRAM fields, then a
bounded NUL-terminated panel name at offset20 with4-byte property padding. It
provides no width/height/stride. Conflicting or duplicate metadata is rejected.
The separate videolfb-base_h/base_l/videolfb-vramSize (or vramSize) properties use
big-endian FDT cells and must be complete if present. Framebuffer.present bits
are1=range,2=width,4=height,8=stride,16=MediaTek found/fps metadata.

The actual dumped stock DT parses, including its six dynamic reservation bounds,
but its512MiB memory placeholder cannot supply the required allocation. Only a
real bootloader-updated RAM map can satisfy the physical loader. Synthetic larger
maps are host-test fixtures, not observations of the phone's runtime handoff.

The separately captured physical runtime FDT (SHA256
``3f70e9fd742e7bff2b6f4fbf7eaa79887f602def295f4b8b88d93f649d267c30``)
has166225 bytes and declares RAM0x40000000+0x180000000. Image5's original parser
returned range-error at the empty placeholder above, matching captured trace
phase254/previous4/detail261. The fixed parser accepts that exact captured tree
and retains all25 exclusions:19 actual reg reservations and6 complete dynamic
allocation intervals. Its chosen512MiB window is [0xd0000000,0xf0000000), which
does not overlap any exclusion, the captured DTB at0x47880000, the15918304-byte
Image5 source at0x40080000, or the recorded framebuffer. The framebuffer metadata
also has an exact independent reg reservation, but hardware scanout admission
still requires the loader's separate MMIO checks.

runtime-fdt-placeholder-evidence.json records before/after host execution,
source hashes and range metadata; no raw proprietary DTB is committed. Run the
private capture regression with ``MTK_RUNTIME_FDT=/private/runtime.dtb`` set.
All23 FDT tests pass, including synthetic placeholder/malformed/populated cases.
These results prove parsing/window admission only; no loader rebuild or further
physical console, relocation or XNU-entry success is claimed by this fix.

Host tests (compile shared object in a temporary directory, no hardware I/O)::

  python3 -m unittest discover -s tools/mt6762/physical -p test_fdt_handoff.py -v
