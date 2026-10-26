MT6762 private export manifest
==============================

Kernel41 completes the build with make exit0 and all export checks passing.
The board-specific Private.arm64.mt6762.exports lists the private ARM64
interfaces compiled for MT6762. It omits35 Apple hardware interfaces identified
by the earlier export audits:18 DART/SART/PPL IOMMU functions and17 UAT C++
symbols. The existing MT6762 configuration has no implementations for these
Apple-specific devices. This change does not supply an Apple IOMMU interface
or enable loading an Apple DART/UAT driver on MediaTek.

config/Makefile selects this manifest only for Private on MT6762. Other symbol
components and machine configurations retain their existing selection. The
regular public and private export validators still check every selected export,
including aliases and wildcard entries, against the linked kernel. A separate
comparison confirmed that the new list is the original private ARM64 list
minus exactly those35 absent symbols.

Once the export mismatch was resolved, the Linux cctools port exposed a second
failure: it seeks when writing its output, so /dev/null failed with Illegal
seek. Both validation calls now write regular files under the configuration's
build directory. The successful artifacts are check-public-exports.symbolset
and check-private-exports.symbolset. They are validation outputs; normal
symbolset generation remains in place. build40.json retains the failed run,
and build41.json records the fully passing retry.

The kernel interfaces were generated with the previously verified genuine
Apple IIG outputs; no new header/interface input was introduced in this change.
