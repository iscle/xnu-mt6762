Export and symbol-set failure audit
==================================

The full build log at evidence/builds/20261023T233612Z-1575920/make.log links
the MT6762 kernel but fails export verification and IOKit/Libkern/Private symbol
sets. This audit does not alter the kernel, exports, toolchain or generated
objects. exports-build20.json records all 131 missing names, their mangled ABI
and export files, category counts, relevant source/toolchain hashes and object
definition counts. No SDK headers, binary objects or proprietary implementations
are included in this package.

config/Makefile:117 generates allsymbols using nm -gj on the linked kernel.
The resulting 22,586 names exactly match a new LLVM nm read of that kernel.
The failure is not an omitted import file or a demangler mismatch. Three block
pointer signatures have equivalent cctools/LLVM text rendering; the audit maps
their actual mangled names. Every diagnosed export is absent from the kernel.

Missing implementation categories
--------------------------------

* 94 DriverKit generated methods/metaclass ABI entries. The local executable
  toolchain/hackios-build/xnu-deps/host/bin/iig is a shell shim, not Apple's IIG.
  It copies pre-generated macOS13.3 SDK headers and emits an empty implementation
  when iig-impl/<Class>.iig.cpp is absent. Sixteen of seventeen compiled .iig.cpo
  objects are 808 bytes with zero global definitions. Only OSObject.iig.cpo has
  definitions (225). Thus these methods were absent before linking, rather than
  dead-stripped or generated under another mangling.
* That aggregate OSObject implementation comes from
  toolchain/hackios-build/xnu-deps/gen-iig-stubs.py, which consumes a link-time
  undefined-symbol list. It forwards some methods directly to kernel _Impl
  routines and emits 44 functions returning kIOReturnUnsupported. Export-only
  wrappers, Invoke methods and callback metaclasses not referenced by the link
  are never generated. This explains why linking succeeds while ABI export
  verification fails. The existing shim also does not implement real user-space
  DriverKit RPC dispatch; a successful GUI boot does not test that facility.
* 17 IOUnifiedAddressTranslator methods/class symbols and 18 Apple PPL/IOMMU,
  NVMe/SART/DART/UAT descriptor exports lack implementations in the supplied open
  ARM source. Their presence in Private.arm64.exports does not provide an MTK
  equivalent implementation. They are separate from the IIG problem.
* Two generic pmap queries have declarations and exports but no ARM definitions:
  _pmap_has_iofilter_protected_write and _pmap_cs_configuration.

Smallest real fix candidates
---------------------------

Replace the IIG shim with complete generation for the actual .iig inputs and
matching interface/compiler version, or use verified complete matching generated
implementations. Remove the aggregate stand-in only when replacing it with
that real generated output, to avoid duplicate metaclass/wrapper definitions.
The shim uses a macOS13.3 SDK while this kernel declares Darwin22.5; both are
from the Darwin22 family, but exact generated-interface compatibility has not
been established. Header availability does not supply absent RPC marshalling/dispatch.
Adding export names to gen-iig-stubs.py would make verification appear better
while leaving required behavior missing; it is not a proposed fix.

The 35 Apple hardware-private entries need real corresponding implementations
if retained as required ABI. A separate, explicitly justified MT6762 export
contract could be considered only after auditing actual consumers and platform
requirements; deleting names merely because verification fails is not justified.
MediaTek IOMMU support cannot truthfully pretend to implement Apple DART/UAT
hardware descriptors. The later bounded shipped-kext import audit is documented
in consumers/README.rst; its missing donor-kernelcache coverage prevents a
complete consumer claim.

The two pmap queries have a narrower potential correction:

* pmap_has_iofilter_protected_write is documented at osfmk/vm/pmap.h:847 as a
  capability query for register-level guarded-mode MMIO writes. The existing
  ARM pmap implementation has pmap_in_ppl returning false and
  pmap_iofilter_protected_write panicking as unsupported near lines12352–12362.
  MT6762.h defines NO_MONITOR=1; its board_config branch enables neither
  XNU_MONITOR nor PMAP_CS. A MT6762/non-monitor implementation returning false
  would report the existing capability accurately, rather than simulate a write.
* pmap_cs_configuration is documented at osfmk/vm/pmap.h:892 as a limited subset
  of non-default pmap-CS policy flags. The documentation explicitly says zero
  does not imply security or even default policy. The x86 unsupported-platform
  definition returns zero. A corresponding MT6762 implementation is plausible
  only under the existing no-pmap-CS/no-monitor configuration, with this limited
  meaning; it must not claim AMFI or code-signing enforcement is secure.

osfmk/vm/pmap_cs.h:57 derives PMAP_CS_INCLUDE_CODE_SIGNING from PMAP_CS, and
lines61–65 derive PMAP_CS_PPL_MONITOR from XNU_MONITOR. The supplied source tree
contains no ARM or IOKit callers of either query: exact-name searches find only
the common declaration, x86 definition and export. Possible external consumers
remain unexamined. Future definitions should be explicitly scoped to the actual
non-monitor policy so they cannot silently answer for a future secure-pmap
configuration. No such definitions were added in this audit.

Build21 implements these two queries only for ARM64_BOARD_CONFIG_MT6762, with
a compile-time rejection if XNU_MONITOR or PMAP_CS_INCLUDE_CODE_SIGNING is
enabled. The linked query bodies each return zero directly; no policy or MMIO
write behavior changes. exports-build21.json records the observed reduction
from131 to129 missing names, with the import list still matching the kernel.
The remaining94DriverKit and35Apple hardware-private names are unchanged.
No exports were removed and full symbol-set verification still fails.

The build21 parallel log has one SYMSET progress message interleaved inside an
export diagnostic. The audit reconstructs that exact recognized two-line
record, validates its full mangled name against the export file, and retains
both original lines plus the reconstruction in JSON. The same full error also
appears intact elsewhere in the log. It is not a new missing symbol. The
build20 baseline report remains unchanged.

Reproduction
------------

Run audit_exports.py with --xnu, --build-log, --deps, --llvm-bin and --output.
The script only reads the existing linked kernel/objects/source and invokes nm
and cxxfilt; it writes one JSON report. Re-running after a new build produces
evidence for that build and must not be mistaken for reproducing the original
binary hash. Full symbol-set verification remains failing until the actual
missing implementations/contracts are resolved.

Build22 genuine IIG integration
-------------------------------

The fresh build22 uses all17 implementations produced by Apple's signed
DriverKit440 IIG from the exact source bundle, with the separately pinned
legacy24-byte IORPC adaptation. The complete previous BUILD and dependency
libraries were preserved. No shim translation unit was reused. All17 generated
objects compile, the kernel links, and exports-build22.json records only35
remaining Apple hardware-private names: all94 missing DriverKit exports were
resolved without deleting exports. The import list still matches the kernel.

The kernel includes an opt-in DEVELOPMENT-only generated-method test. Real
IOMemoryMap::_CopyState_Invoke and OSAction::Aborted_Invoke run193 cases, covering
normal/overlapping/4-byte-aligned buffers, one-way calls, all truncated request
and reply capacities, malformed headers/references, and reply canaries. Both
one-core and eight-core native boots passed; repeated sysctl reads retained
the one-shot result. Without mt6762_iig_selftest=1, both read-only sysctls return
ENOTSUP. An eight-core native MSDC read-only smoke also passed. These bounded
tests do not exercise every generated method or prove full wire compatibility.
The precompiled Apple userspace GUI regression is recorded separately.

The normal Xcode15 replay gate remains strict. Experimental generation requires
the explicit experimental_legacy_replay.py command and pinned input, pristine
generation and transform manifests; neither diagnostic nor transformed status
is rewritten as normal acceptance. build.sh records selected IIG sources before
and after compilation and refuses a different generator/input set in an existing
BUILD tree. iig-build-mode-guard.json demonstrates that reverting implicitly to
the inherited shim is rejected before dependency/header rebuilding.

Build23 closes the reviewed CheckForWork zero-object-reference hole in both
its outgoing wrapper and Invoke reply checks. A bounded header alone does not
authorize objects[0]. Its205-case real-handler suite adds12 CheckForWork cases
and passes on one/eight cores; disabled mode and the eight-core MSDC regression
also pass. The normal generator gate remains unchanged. Build-mode fingerprints
now cover imported replay/transform/profile/helper sources, and every selected
replay build revalidates the complete current input closure before dependencies
even if make could reuse all generated pairs. Build22 artifacts and its
intentionally interrupted GUI run remain retained under their original hashes.

Retained consumer follow-up
--------------------------

The independently parsed import tables of11 retained donor Mach-O images
contain no references to the35 remaining names; LLVM agrees with all11
inventories. Five are actual kext images and six are userspace plugins. The
donor kernelcache and eight standalone bundle executables are absent from
this inspected inventory, so it cannot establish that no donor consumer exists.
The current loader supplies one linked kernel and RAM disks, with no external
Driver- entries or prelinked collection. Frozen build22's PRELINK segments are
empty. See consumers/README.rst for hashes, scanner tests and limits; no export
was removed and no Apple hardware descriptor was replaced by an MTK stub.

Build23 GUI regression
----------------------

The unchanged precompiled Apple executable/cache inputs also reached the home
screen in a completed630-second single-core run using synthetic native
peripherals. The last sampled logo was390.623s and first sampled home400.658s.
All10 scheduled input actions completed, with no observed kernel panic.
Volume HID down/up events reached backboardd. Later power events preceded
modeled off/black and on/lockscreen transitions; the final frame is home.
See ../evidence/native-gui1-build23.json for frame hashes and bounded evidence.
The inherited auto-unlock shim remains, blank widgets/missing services remain,
and this establishes neither real hardware behavior nor measured battery SOC.
