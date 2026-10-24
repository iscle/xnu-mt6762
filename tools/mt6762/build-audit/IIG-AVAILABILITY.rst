Genuine IIG availability and production route
============================================

This bounded investigation found no runnable genuine Apple IIG or complete
generated kernel RPC implementation among the local references/toolchain. It
installed nothing, downloaded no SDK/archive, and changed no kernel source.
iig-availability.json records paths, hashes, repository/API observations and
the exact scope. It does not claim that no unsearched archive could exist.

Local findings
--------------

The two local host/bin/iig files are the previously audited shell shim. PATH
contains no iig, xcrun or darling. The sailfish reference's research/xcode15,
research/xnu-build and research/kdk directories are absent, as are the checked
/Applications/Xcode.app and /opt/darling paths. The reference tree contains one
aggregate stand-in .iig.cpp. The stale iPhoneOS build tree contains 34 generated
files: 32 empty shim translation units and two copies of the aggregate stand-in.
None supplies the missing complete RPC implementation.

The supplied `sailfish local build script
<https://github.com/joranv1/ios-sailfish/blob/main/tools/xnu-build-local.sh>`_
names Xcode15 and explains that Xcode16+ IIG emits IORPC.kernelContent, which
xnu-8796 lacks. Its workflow likewise selects an Xcode15 toolchain and packages
a buildtree containing generated sources. These are useful author-provided
compatibility observations, not an independently reproduced IIG run here.
The GitHub API currently returned zero workflow runs, zero artifacts and zero
releases for that repository, so there is no available generated buildtree to
retrieve through those published channels. A local workflow recipe is not
evidence that its required tool or output exists in this workspace.

Official source boundary
------------------------

The complete, non-truncated official Git tree for xnu-8796.121.2 contains the
17 DriverKit .iig inputs, but no .iig.cpp implementations or IIG generator tree.
The official `DriverKit Makefile
<https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-8796.121.2/iokit/DriverKit/Makefile>`_
generates headers and implementations through an external IIG invocation.
The corresponding `MakeInc.cmd
<https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-8796.121.2/makedefs/MakeInc.cmd>`_
locates that executable through xcrun for the selected SDK. Apple's public
`Developer Tools project manifest
<https://raw.githubusercontent.com/apple-oss-distributions/distribution-Developer_Tools/main/.gitmodules>`_
does not list an IIG project. Those checked sources provide interfaces/build
rules, not a public generator implementation. This supports a precise missing
input finding without an exhaustive claim about every Apple repository.

`Apple's DriverKit guide
<https://developer.apple.com/documentation/driverkit/creating-a-driver-using-the-driverkit-sdk>`_
describes the Xcode template's C++ and .iig inputs. It does not provide the
missing version-matched generated kernel implementations for download.

Concrete production route
-------------------------

The reference uses a macOS worker with genuine Xcode15 as its compatibility
candidate. This is a code-generation task: Apple userspace remains precompiled,
and the Linux MT6762 kernel build can continue consuming generated C++ sources.
It does not require replacing any userspace library or submitting guessed ABI
stubs. The user confirmed that Xcode15 is unavailable on the supplied Mac.

Update after the bounded local search: the user supplied access to a Mac with
Xcode26.6 / DriverKit-440 IIG, and its Apple-anchor signature verification
passed. It is not the reference's Xcode15 toolchain. Full diagnostic generation of all17 interfaces succeeded with the original
source flags, producing34 files with verified transfer hashes. The successful
26c generation manifest is pinned by SHA256
e7a5ada653deb73c997d22994fc0db0db39aef2268297c3cb6b1a407f9d402cf.
All95 method IDs match the older SDK headers. This result remains ineligible
for the normal Xcode15 replay gate. A separately reviewed source transform
adapts the generated kernelContent use to the original24-byte IORPC; its
experimental build/runtime validation is tracked under ../../iig/. SDK26.5 lacks availability.pl, so the
explicitly pinned public AvailabilityVersions-115.4 helper is staged only in the
new output's support directory. No SDK installation or kernel import occurred.

1. Pin the exact current xnu-8796.121.2 source plus relevant port modifications
   and record hashes of all 17 .iig files, IORPC.h and included interface headers.
   Use a separate output directory; preserve the current tested build.
2. On the macOS worker, record xcodebuild -version, xcrun --sdk macosx
   --show-sdk-path, xcrun --sdk macosx --find iig and the actual IIG executable
   hash. Select the Xcode15 Developer directory explicitly. Do not silently use
   the newest installed toolchain; the reference identifies an ABI change.
3. Reproduce the repository's DriverKit generation phase using its real include
   dependencies and deployment definitions. Its rule passes --def, --header,
   --impl and --framework-name DriverKit, followed by C++17 include/sysroot
   arguments, __IIG=1, DRIVERKIT_PRIVATE=1, PRIVATE_WIFI_ONLY=1 and the actual
   XNU_PLATFORM_* define. The26c manifest retains the exact expanded commands.
   The source include paths and prepared BSD/exported headers match the input
   bundle; invoking a tool against an unrelated installed DriverKit SDK alone
   would not be equivalent.
4. Return only the resulting matched 17 headers/17 implementations and their
   provenance manifest for review, rather than a large SDK or a whole userland.
   Confirm genuine RPC marshalling/dispatch bodies and compatibility with the
   existing IORPC layout. The newer-tool kernelContent dependency requires
   a bounded adaptation or matching toolchain; removing layout checks alone
   does not establish compatibility.
5. Replace the aggregate shim as a unit with the genuine outputs; leaving both
   would duplicate metaclass/wrapper definitions. Compile with the existing
   ARM64 ABI, check all 94 missing generated exports and run representative
   dispatch/Invoke argument-validation paths. Symbol presence alone does not
   prove working RPC behavior.

This route addresses DriverKit generation only. The separately missing Apple
hardware-private implementations/export contract remain unresolved. Re-running
the undefined-symbol stub generator or deleting required exports is not a
production substitute for either requirement.
