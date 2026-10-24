Verified Linux IIG replay (integration pending genuine Xcode 15 output)
=====================================================================

``replay.py`` implements the DriverKit Makefile's ``IIG`` command interface.
It never generates RPC methods or substitutes success/unsupported stubs. The
producer is ``../build-audit/iig/workflow.py``. Only source-generation bundles
for Darwin 22.5.0, xnu-8796.121.2, iPhoneOS and all 17 interfaces are accepted.

The normal Xcode15 route has not run. Genuine Xcode26.6 diagnostic output is
now available for all17 interfaces. A separate explicit experimental consumer
validates a reviewed legacy IORPC adaptation; see LEGACY-CANDIDATE.rst. It does
not weaken this normal consumer's version/provenance gate. One normal transport
unit test mocks opaque bytes only to test copying; actual candidate validation
and kernel-handler execution have separate tests and evidence.

Trust and validation
--------------------

After trusted transfer from the selected Mac, independently record/review the
SHA256 of both ``inputs.json`` and ``generation.json``. Environment settings::

  export MTK_IIG_XNU=/path/to/xnu
  export MTK_IIG_INPUTS=/path/to/input-bundle
  export MTK_IIG_GENERATED=/path/to/generated-bundle
  export MTK_IIG_INPUT_SHA256=<reviewed-input-manifest-sha256>
  export MTK_IIG_GENERATION_SHA256=<reviewed-generation-manifest-sha256>
  export MTK_IIG_OUTPUT_ROOT=/path/to/xnu/BUILD
  export IIG="$MTK_IIG_XNU/tools/mt6762/iig/replay.py"
  "$IIG" verify
  "$IIG" plan > /new/evidence/location/iig-transition-plan.json

Both manifests are pinned, not trusted merely because an adjacent hash can be
recomputed. The Mac must record successful Apple-anchor codesign verification
of the generator. Linux validates that recorded provenance against the pinned
manifest; it cannot independently rerun Apple's signature verifier. The JSON
is not itself a cryptographically signed attestation. The bundle hash therefore
requires trusted transfer/review. SDK/tool binaries remain on the Mac.

Every replay rechecks the full source header/interface inventory against both
the input bundle and current checkout, the producer script hash, exact generator
commands/platform flags, both support headers and all 34 generated outputs.
Known placeholder markers, empty files, incompatible ``IORPC.kernelContent``
references, and missing class-specific Invoke definitions are rejected. Genuine
dispatch routines may return ``kIOReturnUnsupported`` for unknown methods; that
constant is not forbidden. These structural checks do not establish RPC behavior,
ABI correctness, successful compilation or a passing export audit.

Only matching ``--def Class.iig --header Class.h --impl Class.iig.cpp`` pairs
are accepted. Output must be in the configured build directory, never a source
subtree, and output symlinks are rejected. All validation completes before output
replacement. Each replacement is atomic; the header (make's primary target) is replaced last.
Interruption between the two files requires rerunning the target. Unsupported flags fail instead of being ignored.

Controlled transition (not executed by these tools)
---------------------------------------------------

The read-only ``plan`` inventories existing generated pairs and linked kernels
with hashes. Preserve the entire previous BUILD directory under a unique name,
then create a fresh BUILD directory and rebuild dependency libraries/exported
headers with the verified ``IIG`` environment inherited by setup and make. This
avoids stale generated pairs, object files, dependency tracking and exported
header copies from the previous shim mode. Preserve the tested kernel and its
source/build evidence. Do not delete or overwrite the old tree as a shortcut.

The parent build integration must record selected manifest hashes in build
results and must not call ``gen-iig-stubs.py``. These scripts do not perform the build-directory transition themselves; the
parent build integration records and controls that separate step. Genuine generation, compile/link, remaining export
checks, and bounded native boot acceptance are separate future gates; a linked
kernel with missing exports is not a fully passing build.

Run the guard suite with::

  python3 -m unittest discover -s tools/mt6762/iig -v

Explicit diagnostic-26 legacy experiment
---------------------------------------

A separate executable, ``experimental_legacy_replay.py``, now accepts only the
pinned genuine DriverKit-440 diagnostic generation plus its exact reviewed
legacy transform candidate. It does not change normal ``replay.py`` eligibility.
Set the normal MTK_IIG_* input/generation/root variables above, plus::

  export MTK_IIG_CANDIDATE=/path/to/iig-legacy-candidate26c-2
  export MTK_IIG_CANDIDATE_SHA256=<reviewed-transform.json-sha256>
  export IIG="$MTK_IIG_XNU/tools/mt6762/iig/experimental_legacy_replay.py"
  "$IIG" verify

The experimental verifier checks the complete current source inventory, pinned
input/generation/candidate manifests, Apple-anchor tool verification and commands,
pristine outputs, transform/profile/helper source hashes, exact operation counts,
and every candidate output against a fresh in-memory recomputation of the
reviewed transform. It installs the compatibility helper adjacent to each
implementation atomically before the implementation/header pair. All validation
finishes before any output changes. It does not edit pristine outputs or source
interfaces. It still labels the candidate as experimental, with compilation and
RPC behavior unverified until separate build/runtime acceptance.

Eight integration tests use the actual preserved candidate, including tampered
implementation/helper rejection, exact LOCAL Create_Call evidence, helper-output
symlink rejection and normal-policy rejection of diagnostic output. They skip
explicitly when the artifact is unavailable; they never invent an RPC substitute.
The earlier normal-path tests cover 18 guard/transport cases. Genuine all17
outputs now exist and the separate compatibility report records 95 unchanged
method IDs; the original old generated implementation needed for a complete
wire-layout comparison remains unavailable. Consult the compatibility report
and LEGACY-CANDIDATE.rst for the remaining limits.
