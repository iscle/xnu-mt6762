Retained donor consumer audit for the 35 build22 exports
======================================================

No exact import consumer was found in the inspected artifacts. This is a
bounded negative result, not evidence that the complete iOS donor has no
consumers. The donor kernelcache is not retained under the searched project
root; its embedded Apple hardware drivers were therefore not audited. No
exports, stubs, kernel code, original Apple binaries or IIG inputs were changed.

Inventory and method
--------------------

``donor-ios165.json`` records all 96 regular files under the retained
``runtime/ios165/rootfs/System/Library/Extensions`` with sizes and SHA256, all
18 Info.plist bundle records, eight missing standalone executable paths, and
all 11 Mach-O64 images. Five images are MH_KEXT_BUNDLE:

* ASIOKit.kext/ASIOKit
* AppleGameControllerPersonality.kext/AppleGameControllerPersonality
* AppleUserConsent.kext/AppleUserConsent
* AppleUserConsent.kext/AppleUserConsent_development
* lifs.kext/lifs

The remaining six images are MH_BUNDLE user-space plugins (AppleMesaLib,
AppleHPMLib, FastpathLib, EAP-RSA, IOStreamLib and IOUSBLib). A directory ending
in .kext is not by itself evidence that every contained image executes in the
kernel. Missing standalone executables may be shared-cache residents; they are
recorded as absent from this directory, not asserted absent from iOS.

The input list is exactly the 35 mangled ABI names in ``exports-build22.json``;
its hash and complete target list are retained. The scanner independently
parses LC_SYMTAB undefined external entries, classic dyld bind streams where
present, and LC_DYLD_CHAINED_FIXUPS import tables. It compares complete names,
without demangler ambiguity or substring matches. LLVM21 llvm-nm separately
checks the undefined-symbol sets; its executable hash/version and per-image
output hash/count are recorded. All 11 independent symbol inventories agree
with LLVM. All six user-space images additionally have parsed chained import
tables. Across the 11 images there are 1,183 per-image unique import entries
(not 1,183 globally unique names), zero target hits and no parse-coverage errors.

The REA native provider was previously unavailable. The established LLVM and
format-aware offline fallback was used without configuration changes or target
execution. Only hashes, metadata and exact symbol names are packaged; no
proprietary binary payload or disassembly is included.

The complete project filename search used rg --files --hidden --no-ignore with
kernelcache/prelinked/.kc/.ipsw patterns. Its sole candidate was XNU's source
test ``tests/vm_kern_count_wired_kernelcache.c``, not a donor cache. The JSON
retains that result rather than silently dropping it. Renamed files, external
mounts and symlink targets outside the searched tree are not excluded by this
filename search. No cache was downloaded. Compressed/encrypted/fat/fileset
images, if explicitly supplied, must be decoded or audited with a suitable
provider; unsupported formats are reported as coverage gaps, never no-hit
successes. String-only matches and dynamically constructed symbol lookups are
not treated as proven imports. A chained import table declares a dependency;
it does not prove runtime reachability.

What the current port actually loads
-----------------------------------

``loading-build22.json`` pins the frozen linked kernel to the exact SHA256 in
the export audit, and records the inspected source hashes/line locations.
Its __PRELINK_TEXT, __PRELINK_INFO and __PRELINK_DATA segments all have zero
file and VM sizes. It has no LC_FILESET_ENTRY commands, no kxld symbol names,
and contains the compiled diagnostic refusing non-prelinked kext linking.
The exact-name source search across bsd/osfmk/iokit/libkern/libsa/pexpert
implementation files finds no direct use of these 35 names (matching the UAT
class name for C++ entries). Export declarations remain separately present.

The current ``boot/prepare.py`` loads one linked Mach-O's segments and describes
RAMDisk entries in /chosen/memory-map. It does not add Driver- entries for
standalone Apple kexts or construct a donor prelinked collection. The source
still contains real OSKext and catalogue machinery: libsa/bootstrap.cpp can
read prelinked collections or booter Driver- entries, then loads available
kernel components and built-in personalities. OSKext::loadExecutable handles
prelinked objects separately; its non-prelinked linker requires CONFIG_KXLD,
otherwise returning a link error. Thus finding OSKext load methods in the
source does not demonstrate that this boot loads the retained Apple kexts.
The current RAM-root image merely containing them is likewise not a loader.
This is source/frozen-image evidence, not a runtime loaded-kext enumeration.

These observations explain why missing external export names need not block
the already-linked current boot: no unresolved static use of them was found,
and the current producer supplies no such external driver collection. They do
not justify deleting the names from the intended ABI, nor establish that a
future driver/storage/GPU configuration will not require a real implementation.

Hardware meaning and platform requirement
-----------------------------------------

The 35 names split into 17 IOUnifiedAddressTranslator class/method entries,
seven pmap_iommu operations, and eleven NVMe/PPL, SART, DART and UAT descriptor
or translation helpers. The descriptor names explicitly identify Apple
hardware families (including t8020/t6000/t8110); they are not MediaTek register
contracts. No actual retained consumer here supplies a body or hardware
semantics for them. In particular, an implementation of an MTK IOMMU cannot
truthfully be labelled as an Apple DART descriptor merely to satisfy exports.

The seven pmap_iommu operations and UAT class names are broader interface
names. This audit cannot classify every possible user as Apple-hardware-only
from spelling alone: they require the missing consumer code and an actual ABI
contract. MT6762 drivers still need correct DMA ownership and any required
native address translation, independently of these absent implementations.
Neither this no-hit inventory nor a successful boot substitutes for those
requirements. Full donor-kernelcache consumer coverage and platform-specific
contracts remain necessary before considering any export-policy change.

Reproduction
------------

From this directory::

  python3 scan_consumers.py --exports ../exports-build22.json \
    --extensions /path/to/ios165/rootfs/System/Library/Extensions \
    --llvm-nm /path/to/llvm-nm --search-root /path/to/project \
    --output /new/donor-ios165.json
  python3 audit_loading.py --xnu /path/to/xnu \
    --loader /path/to/boot/prepare.py --kernel /path/to/frozen-build22/kernel.macho \
    --exports ../exports-build22.json --llvm-nm /path/to/llvm-nm \
    --output /new/loading-build22.json
  python3 -m unittest discover -s . -p test_scan.py

The five host tests cover undefined-vs-defined/debug symbols and exact matching,
malformed symbol-table bounds, all three chained-import formats, bind-operation
requirements, unsupported bind opcodes and unterminated chained names. They do
not execute donor code. All five pass.
