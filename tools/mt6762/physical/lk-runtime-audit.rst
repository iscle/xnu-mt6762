Exact LK state and temporary-boot integration
============================================

This read-only follow-up resolves two distinctions that the supplied older BSP
alone cannot establish. ``audit_lk_runtime.py`` pins the dumped LK hash and
emits12 fully decoded ranges,25 static command registrations, two selected
direct-call references, cache-table metadata and public seccfg header fields.
It neither generates nor writes a patched image or security configuration.

Warning source identified before the temporary boot
--------------------------------------------------

In the exact LK, seccfg header offset0xc is the lock-state word. Its getter is
0x48052864. Header offset0x10 is read by0x48052934 and written by0x48052994;
those routines are used as dm-verity status operations by
``get_dm_verity_status`` at0x48016650 and ``clear_dm_verity_status`` at0x480166dc.
The setter recalculates header authentication through0x48052728 before writing.
The exact field use takes precedence over a third-party tool's field names.

The captured states are:

====================== ================ =====================
Capture                Lock at0xc       dm-verity status at0x10
====================== ================ =====================
Before unlock          1                0
Immediately unlocked   3                1
After temporary trial  3                1
====================== ================ =====================

Thus a corruption-status input was already set by the unlock operation before
the attempted XNU transfer. This explains the warning without inferring an
actual system-partition hash mismatch. The later managed-verity persistent
record is another warning input, generated from this status. The exact warning
handler0x48049b40 displays the warning if the status is1 **or** the passed AVB
hashtree mode is2 (EIO). Removing only the persistent AVB record does not clear
an existing status1.

The status getter also recognizes hardware SECURITY_AO register0x1001a088 bit0
or cached WDT NONRST_REG low-nibble reason4 as corruption, persists status1,
then clears that SECURITY_AO bit. A source-only restoration analysis therefore
must distinguish current status from a fresh hardware event that could set it
again. No register reads or writes were performed by this audit.

Exact built-in clearing behavior
-------------------------------

The exact LK's clear routine is more extensive than the older supplied BSP:
it initializes the persistent-value context, writes32 zero bytes to
``avb.managed_verity_mode``, persists that change, clears SECURITY_AO bit0,
and calls the authenticated seccfg setter with zero. A following ordinary AVB
comparison can recognize the zero digest as a different OS instance and remove
the stale managed record. The platform handler reaches this clear routine from
its OTA-success branch, not from a recovered fastboot clear command.

There is no explicit verity-clear command among the25 recovered static
fastboot registrations. The direct Thumb-call scan has one caller of the
clear routine,0x48049be0, in that platform handler. This bounded scan does not
claim a complete graph of arbitrary indirect extensions. It does not justify
trying undocumented commands or manufacturing an OTA result.

For a separate, explicitly authorized repair implementation, the minimal
persistent semantics are: retain lock3 and all unrelated current fields; clear
the actual dm-verity status word with valid header authentication; remove or
clear only the named stale AVB record while preserving any other records.
Restoring the original locked backup would relock the device and is not the
same operation. Merely editing four authenticated bytes without recomputing
the integrity field is invalid. This audit supplies no mutation tool or phone
command, and does not claim the current post-recovery image has been reread.

Why the current fastboot payload cannot solve its own entry failure
-----------------------------------------------------------------

The cache table at0x480ab510 has a boot/recovery entry and a vendor_boot entry.
Each has aliases at offsets0..8, an image pointer at0xc, a size at0x10, and
allocator/free callbacks at0x14/0x18. The boot allocator accepts sizes up to
128MiB and delegates to the LK allocator; vendor_boot uses a reserved-memory
allocator. Both cached pointers are zero in the dumped image.

The allocator at0x48037c50 selects an entry by name, releases any prior cached
buffer through its matching callback, allocates the requested size, then records
pointer and size. The only recovered direct caller is0x48049f94 in the normal
verified-image loading path. That path copies the image to the returned buffer
at0x48049fb0, then calls the decapsulator at0x48049fc2. The fastboot path omits
this allocation/copy sequence. Its decapsulator requires that cache and ignores
the supplied download pointer, as the observed pre-XNU panic demonstrates.

No recovered non-flashing command populates this cache and returns to fastboot
for a subsequent downloaded image. ``continue`` resumes normal stock boot; it
is not evidence of a cache-preparation operation followed by a safe return.
The scan covers direct Thumb BL/B.W calls over LK file0x280..0x58000; indirect
calls and a modified running LK are explicitly outside that proof boundary.

RAM-only adaptation design and subsequent offline implementation
----------------------------------------------------------------

The following design was subsequently implemented and tested in
``lk-cache-bridge/``. That bounded model resolves the cache-call mismatch;
physical RAM placement and an execution transport remain unverified.

If the parent establishes a supported way to execute a modified LK solely in
RAM, a narrow adapter at the fastboot decapsulator call can mirror the existing
normal path:

1. Verify exact original LK identity/instructions and an independently safe
   executable-RAM area. Preserve the original handler's registers and calling
   convention; downloaded pointer is r7 and byte count is sb at this callsite.
2. Validate the complete downloaded boot-image bounds before copying. Reject
   sizes outside the cache allocator's bound and unsupported header layouts.
3. Call the existing allocator with the literal ``boot`` and downloaded size,
   reject a null return, and copy the full bounded download into the returned
   buffer, as the normal verified-image loader does.
4. Invoke the existing decapsulator and resume the handler with its required
   preserved registers. Existing error paths must remain failures.
5. Apply instruction/data cache maintenance before execution and prove this
   path in an isolated model before another physical attempt. Audit later
   teardown/decompression/DTB behavior and allocator lifetime; clearing this
   first panic does not prove the remainder boots.

Do not alias the cache pointer directly to fastboot's download buffer: its free
callback and ownership differ. Do not patch a zero pointer into an unchecked
success or change the persistent LK partition for this temporary-boot design.
There is currently no implemented or validated physical RAM entry route, so
the offline bridge is not a ready-to-run physical payload.

Reproduction
------------

From the XNU tree::

  python3 tools/mt6762/physical/audit_lk_runtime.py \
    --dump /path/to/mini_iphone_dump_2 \
    --trial /path/to/mtk-unlock-20261024 \
    --output /tmp/lk-runtime-evidence.json

Only captured files are read. Capstone is the established REA provider fallback.
No private record contents, firmware blobs or device identifiers are emitted.
