Volatile DA2 heap exclusion for the diagnostic trace
===================================================

This opt-in host transformation reserves [0x4005e2a0,0x40090000) from the
exact selected DA2's allocator. The image5 trace [0x40084000,0x40084100) then
lies below the new heap start. It changes no instruction, BSS boundary, load
address, heap end, signature length or persistent storage. No phone upload or
write has been performed by this package. This is not a flashable LK image.

Exact scope and reference coverage
---------------------------------

The wrapper pins the complete MTK_DA_V5.bin hash, zero-based entry22, hardware
0x6765, DA2 region metadata and original full-region digest. See the manifest
inside offline-evidence.json. The source DA2 has exactly three occurrences of
the32-bit value0x4005e2a0:

* Offset0x120 is startup's BSS end. It remains unchanged.
* Offset0xa340 is the size getter's heap-base subtraction operand.
* Offset0xadf8 is heap initialization's initial block pointer.

Only the last two words change to0x40090000. The fixed end0x68000000 at0xa344
stays unchanged. The new base is64KiB aligned, exceeds BSS end and the entire
trace, and reduces available allocator capacity by0x31d60 bytes. New capacity
is0x27f70000 bytes. Startup BSS remains [0x40051090,0x4005e2a0).

A scan of every aligned ARM and Thumb single-instruction PC-relative LDR
candidate in the pinned region finds exactly four references to these words:
startup0x400000d8→0x40000120, size getter0x4000a338→0x4000a340 and
0x4000a33a→0x4000a344, initializer0x4000add6→0x4000adf8. The initializer
stores the root/size at0x400538a0/+4; the existing allocator consumes its
free-list state rather than separately loading the old base. This establishes
the audited allocator's boundary, not a whole-program proof of every possible
indirect store, address arithmetic or fixed DMA buffer.

Patch ordering and use
----------------------

``reserve_heap.wrap_patcher`` is an explicit wrapper for the existing bound
``xft.patch_da2`` method. It first verifies the original input, calls that
existing patcher, verifies all audited code/literal preimages survived, changes
only the two allocation literals, and invokes a caller-supplied manifest sink.
The wrapper does not install itself and contains no device transport::

  xft.patch_da2 = wrap_patcher(xft.patch_da2, pinned_loader_bytes, save_manifest)

Install it before the existing XFlash patch_da operation: that operation calls
patch_da2 and then fix_hash, so DA1's recorded DA2 hash covers the final reserved
bytes. Applying this transformation after fix_hash would break that linkage.
The caller must require that the wrapper ran and its manifest was retained
before permitting any upload; the stock hash-location-failure fallback skips
patch_da2 and must not silently upload an unreserved image. Do not hook a DA
already running. Existing source mt6762 kernel, mtkclient checkout and phone
state are unchanged by this package.

A pure CLI also accepts a previously produced full DA2 region after the existing
patcher, and writes only new local output/manifest paths::

  python3 reserve_heap.py --loader /path/to/MTK_DA_V5.bin \
    --after-existing-patcher /private/full-patched-da2.bin \
    --output /private/full-patched-reserved-da2.bin \
    --manifest /private/reservation.json

The CLI does not repair DA1's hash; that remains the existing caller's job.
Truncated/signature-stripped input, an already-reserved input, altered audited
code or a different original image is rejected. The manifest separately hashes
the original, after-existing-patcher and final bytes. Additional changes made
by the preceding patcher are preserved and are not disguised as this patch.

Tests and readback plan
-----------------------

Run offline with existing capstone/unicorn modules::

  python3 test_reservation.py --loader /path/to/MTK_DA_V5.bin \
    --mtkclient /path/to/mtkclient --output /private/offline-evidence.json

Four runs execute original ARM BSS clearing and Thumb size/heap-init/allocation
instructions for old/new bases. Only OS critical-section helpers are modeled.
Tests check normal100-byte/1MiB/8KiB/1MiB allocations, exact heap exhaustion,
end bounds, unchanged BSS and trace bytes. The old1MiB allocation contains the
trace; new allocations exclude it. Ten malformed/preimage cases are rejected.
The optional integration check executes the three reviewed pure patch methods
from the installed mtkclient source with a log collector, without importing
its device modules or constructing a client; their source hashes and output
manifest are recorded. That real existing patcher preserves all audited spans.

If the parent later admits this volatile upload, the bounded readback plan is:

1. Preserve the final DA2/full loader manifest and verify the actual selected
   entry and transmitted executable-prefix digest, including the updated DA1
   hash linkage, before upload. Reject an unpatched fallback.
2. On connection read the trace256 bytes immediately, before unrelated DA
   storage operations; never seed or clear the trace during capture.
3. Read only the two runtime literal words0x4000a340/0x4000adf8 (expected
   0x40090000), BSS-end literal0x40000120 (0x4005e2a0), heap-end literal
   0x4000a344 (0x68000000), and initialized root/size at0x400538a0/+4
   (0x40090000/0x27f70000). A mismatch invalidates this retention assumption.
4. Validate the captured trace's exact version, expected payload identity,
   bounds and consistency. Keep raw private evidence and hashes.

Preloader DRAM initialization, DA1/BROM use, reset retention, fixed runtime
buffers and non-heap DMA may still overwrite this interval. A valid marker can
provide positive evidence; absence after reconnection remains inconclusive.
This patch excludes one demonstrated allocator collision and does not claim
to solve those independent retention risks or prove physical XNU execution.
