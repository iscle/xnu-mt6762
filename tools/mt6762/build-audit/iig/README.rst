Code generation with genuine Xcode15 IIG
=======================================

workflow.py prepares a portable source-only input directory/archive, generates
17 interface pairs on a Mac, and verifies their hashes on either host. It
never builds a kernel or userspace, installs software, launches another toolchain
installer, or contacts/boots a phone. Apple userspace remains precompiled.

The Mac generation path follows the checked xnu DriverKit Makefile and the
sailfish Xcode15 compatibility route. The full structured Xcode26.6 / DriverKit440 diagnostic generation completed
for all17 interfaces (34 output files); its26c manifest is retained separately.
The normal Xcode15 route has not run. The diagnostic output requires a separate
legacy ABI adaptation and remains rejected by normal replay. If SDK/header
preparation or genuine parsing fails, the new output directory retains logs
and a failed generation.json. Do not turn that into empty translation units.

Prepare on the Linux checkout, using new paths:

::

    python3 tools/mt6762/build-audit/iig/workflow.py prepare \
      --xnu /path/to/xnu --platform iPhoneOS \
      --output /path/to/new-iig-inputs \
      --archive /path/to/new-iig-inputs.tar.gz

The bundle contains the script, inputs.json and source/ with a conservative
header superset from iokit, osfmk, bsd and EXTERNAL_HEADERS, all17 .iig inputs,
the relevant generation rules, version file and two upstream BSD header helper
scripts. It includes the source DriverKit OTHER_HEADERS, such as IOReturn,
IOTypes and IORPC, and source mach/machine and bsd/machine selector headers.
No SDK, kernel image, binary objects or stand-in generated implementation is
copied. Hashes identify actual working files, including local modifications.
This is larger than a minimal include closure but avoids omitting conditional
source headers. The macOS SDK stays installed on the user's Mac.

Transfer/extract the input bundle using the parent-approved Mac connection.
From that bundle on the Mac:

::

    python3 workflow.py generate --bundle /path/to/new-iig-inputs \
      --xcode /Applications/Xcode_15.4.app --output /path/to/new-iig-generated

The Xcode path is an example; use the user's actual Xcode15 application. The
helper selects its Developer directory through the child environment only,
requires xcodebuild to report major15, resolves SDK/IIG with /usr/bin/xcrun,
requires a Mach-O IIG inside that selected Xcode, and records tool hashes.
It verifies the executable with ``codesign --verify --strict '-R=anchor apple'``
and retains signature details and the generator's version. The provenance field
``iig_codesign`` records ``verified: true`` and ``apple_anchor: true`` only after
that command succeeds.
It does not change xcode-select or the user's environment persistently.

The original BSD helpers produce _posix_availability.h and _symbol_aliasing.h
inside the new output's support/bsd/sys directory. The latter requires the
selected SDK's executable usr/local/libexec/availability.pl unless preparation
explicitly supplies ``--availability-source /path/to/availability.pl``. The
only accepted bundled dependency is public AvailabilityVersions-115.4 commit
5d9baee345b3bc72b26c71adc65f94f2d5e9ced2, SHA256
26842f02be5cb75ab02baa6654153ed0b848ff35122a32fea3a02b8472095234.
Its source is hashed separately from the XNU input inventory. Generation stages
it under the new output's support/sdk/usr/local/libexec and points only the
upstream alias helper at that staging directory. IIG still uses the actual Mac
SDK; no SDK file is modified. Missing or changed dependencies are rejected.
These helpers are needed by genuine IIG during
the upstream installhdrs phase, as documented in bsd/sys/Makefile.

The generator uses the exact source include ordering and definitions from
iokit/DriverKit/Makefile, including the new support/bsd include and
EXTERNAL_HEADERS. OTHER_IIG_FLAGS is empty in this checkout. The manifest
explicitly pins XNU_PLATFORM_iPhoneOS, matching the current port's environment;
the macOS SDK is used for host generator/header dependencies. It does not
silently replace that definition with XNU_PLATFORM_MacOSX, or add KERNEL=1
(KERNEL is an IIG interface attribute in these inputs). No full build is invoked.
Unresolved include dependencies must be diagnosed from the retained command/log
before adding a justified source/header preparation step.

Return the new output directory, then verify it against the original input
bundle on Linux:

::

    python3 workflow.py verify --bundle /path/to/new-iig-inputs \
      --output /path/to/new-iig-generated

Generation requires exactly17 Class.h/Class.iig.cpp pairs under DriverKit/ and
rejects the known aggregate shim, empty translation units and newer-tool
kernelContent output. generation.json records full command argument arrays,
input-manifest hash, Xcode/tool/SDK provenance and every output hash. Verification
does not claim that symbol ABI or RPC behavior has passed compilation/tests.
The separate Linux replay/import integration must check current source hashes,
replace the aggregate shim without duplicates and then test exports/dispatch.

The reference route is documented in ../IIG-AVAILABILITY.rst. No SDK contents or
genuine Apple executable should be added to this repository.

Explicit Xcode26 diagnostic mode
-------------------------------

The available Mac actually has Xcode26.6, not Xcode15. Its DriverKit-440 IIG
successfully generated a single IOUserClient smoke-test pair with the original
flags and pinned public availability helper. This does not prove compatibility
with XNU8796 or the precompiled userspace. The new full diagnostic bundle uses
a distinct ``-diagnostic26`` path; the earlier bundle remains unchanged.

The first structured diagnostic attempt failed its signature check: this Mac's
codesign interpreted separate ``-R`` and ``anchor apple`` arguments as a file
name / invalid requirement. The single argument ``-R=anchor apple`` succeeded
on the same host. The corrected producer is packaged in a new
``-diagnostic26b`` bundle; the earlier bundle and failed-run evidence remain.
This fixes argument handling without weakening the Apple-anchor requirement.

The corrected signature run generated all17 pairs, then the structural checker
incorrectly required IODispatchQueue::Create. Its original ``LOCAL`` interface
instead generates Create_Call and Create_Invoke, with the ordinary local method
implemented elsewhere. The ``-diagnostic26c`` producer retains exact Invoke
checks and accepts a Call wrapper only when both original interface and generated
header declare that method LOCAL, and the header declares the matching Call
method. All34 files from the preserved failed-validation run pass this corrected
structural check; this is not an ABI compatibility finding.

::

    python3 workflow.py generate --bundle /path/to/inputs-diagnostic26 \
      --xcode /Applications/Xcode.app --output /path/to/new-diagnostic-output \
      --diagnostic-xcode-major 26

Only an explicitly requested actual major26 is accepted in this mode. Its
successful status is ``diagnostic-generated-not-compatible``. The generator
still verifies the Apple signature and exact17 pairs, input/output hashes, RPC
content and class-specific Invoke/wrapper definitions. It permits but counts
``kernelContent`` occurrences per output file. Normal ``verify`` and the Linux
replay path reject this status; removing a diagnostic marker cannot pass the
Xcode15 version check. Method IDs, wire structures, IORPC fields, target headers
and compilation/export behavior require separate review before any import.
