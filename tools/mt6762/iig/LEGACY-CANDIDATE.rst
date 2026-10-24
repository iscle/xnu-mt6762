DriverKit440 legacy IORPC transform candidate
===========================================

legacy_transform.py is a separate source transformation experiment. It does
not change genuine generator output, current kernel sources, or replay.py's
Xcode15 admission policy. Its result is labelled
``legacy-transform-candidate-not-compatible`` with ``replay_eligible: false``.
No compatibility or working-RPC claim follows from a successful transform.

The reviewed profile pins every byte of all17 genuine headers and17 generated
implementations. Unknown hashes, missing files, changed pattern counts, or
unhandled kernelContent/parser shapes are rejected before creating output.
The command requires a pinned successful diagnostic generation manifest and
its matching input manifest. Earlier failed diagnostic manifests are preserved
and are not rewritten into successful ones.

The transformed candidate keeps the original24-byte IORPC and adds a compile
time size assertion. Invocation unions use packed Msg_With_Content pointers,
remove their extra kernelContent slot, and access content as a member of that
packed struct. No naturally aligned Content-pointer cast is introduced.
All94 request-bearing Invoke entries call the bounded request helper before
any generated variable-length count reads or content access. All86 methods
whose generator assumed a nonnull reply instead check its pointer and capacity
before continuing. The remaining oneway methods still permit absent replies.
All36 dispatch parsers use the bounded legacy-message helper.
All85 ordinary generated reply producers explicitly set the190615 reply
protocol version; their outgoing caller validation now checks that version.
CheckForWork's request-shaped asynchronous reply is excluded from that check.

Two special paths require additional handling. InterruptOccurred builds a
message directly in a supplied reply buffer, so it checks that buffer before
memset or field writes. CheckForWork returns a request-shaped asynchronous
message in its reply buffer. Both its reply parsers use checked bounds, and
forwarding explicitly assigns the reply buffer to rpc.message before clearing
rpc.reply. The helper's reply argument chooses the buffer; it must not blindly
require the normal reply-version ID for this asynchronous request-shaped path.
Candidate26c-2 also requires at least one logical object reference in both
CheckForWork paths before the outgoing wrapper reads objects[0]. The general
bounded parser accepts an otherwise valid header with zero references; a Mach
descriptor alone does not prove that the content carries an object slot.
Candidate26c-1 remains preserved and cannot pass the updated transform-hash
replay check.

The separately reviewed MTKIIGLegacy.h must provide:

::

    IORPCMessage *mtk_iig_legacy_message(const IORPC &, bool reply = false);
    bool mtk_iig_legacy_request(const IORPC &, uint32_t full_size,
        uint32_t content_offset, uint64_t expected_refs, uint64_t expected_id);

The request helper must validate the actual message bounds and descriptor
traversal, expected content offset, reference count and method ID before typed
member access. A C++ pointer/capacity pair is still an internal trusted-memory
contract; this does not make arbitrary unmapped pointers safe to dereference.
The transform records the supplied helper hash, but does not certify its
implementation. A separate output directory is mandatory and the helper is
copied there as source only.

Host validation exercises all actual17 generated implementations, ordering of
the early checks, special reply paths, unexpected source shapes and manifest
hash rejection. Actual command-line negatives additionally reject changed
pristine source, changed manifest, helper symlink and an existing output
directory, preserving existing contents. If genuine artifacts are absent, those artifact tests are
explicitly skipped; no fabricated RPC implementation substitutes for them.
Method IDs, full packed wire-layout comparison, target compilation, exports,
malformed-message/runtime tests and explicit import review remain independent
acceptance requirements.

An opt-in DEVELOPMENT/DEBUG MT6762 kernel test is registered separately in
iokit/Kernel/MTKIIGLegacySelfTest.cpp. With ``mt6762_iig_selftest=1``, its first
read of ``kern.redwood.mt6762_iig_test_result`` or ``mt6762_iig_test_cases``
runs a mutex-serialized test once. The actual generated public
IOMemoryMap::_CopyState_Invoke and OSAction::Aborted_Invoke methods receive
independently described raw wire buffers and controlled counting handlers.
The205 cases cover separate/overlapping/four-byte-aligned buffers, every short
request/reply capacity, null buffers, invalid descriptor/header/reference/ID
metadata, untouched reply canaries on failure, and a valid oneway call without
a reply. Twelve additional cases call the real
IODispatchSource::CheckForWork_Invoke with a controlled handler that writes
request-shaped replies, including header-only zero-reference, truncated
one-reference, wrong protocol/flags/descriptors, oversize and valid one-reference
messages. No sentinel object pointer is invoked. Expected result is1 with205
cases; a negative result identifies the
first failed case. Without the explicit argument, both reads return ENOTSUP.
The test creates no IOKit objects and accesses no devices. Its source being
present is not evidence of a successful build or runtime test. Build22 passed
the earlier193-case suite on one and eight emulated CPUs; that suite lacked
the zero-reference regression. The new205-case result requires its own run.

Example after independently reviewing the successful diagnostic manifests:

::

    python3 legacy_transform.py \
      --generated /path/to/pristine-diagnostic-output \
      --generation-sha256 <reviewed-hash> \
      --inputs /path/to/input-bundle --input-sha256 <reviewed-hash> \
      --helper /path/to/MTKIIGLegacy.h --output /path/to/new-candidate

The profile contains hashes and structural counts, not redistributed SDK files
or generated kernel implementation bodies. Candidate output stays outside the
repository and current kernel build.

Observed build22 validation
---------------------------

All17 adapted genuine implementations compiled in a fresh kernel build. The
94 previously missing DriverKit exports are now present;35 unrelated Apple
hardware-private exports remain missing. build22.json and exports-build22.json
under ../build-audit record exact source/kernel/tool identities. No original
Apple executable was compiled.

The bounded helper passes host guard-page tests with actual XNU standalone ABI
declarations. Host ASan/UBSan execution was unavailable because libasan was
missing; no sanitizer pass is claimed. The opt-in kernel selftest executes
actual generated IOMemoryMap::_CopyState_Invoke and OSAction::Aborted_Invoke
handlers in193 cases, with PASS on one and eight emulated A53 cores. Disabled
mode returns ENOTSUP. These are representative method tests; all-method wire
compatibility and physical hardware operation remain unproved.

To select the experimental build consumer, use the normal replay environment
plus MTK_IIG_CANDIDATE=/path/to/candidate and MTK_IIG_CANDIDATE_SHA256 containing
the reviewed transform.json digest. Set IIG to experimental_legacy_replay.py,
then run its verify command before building. The build records selected inputs
and rejects a changed generator or bundle in an existing BUILD tree. Preserve
and replace BUILD with an empty directory for a deliberate mode transition.
SDK/tool binaries and generated bundles remain outside the source repository.

Build23 compiled candidate26c-2 successfully. All205 representative actual
Invoke cases passed on both one and eight emulated cores, including the new
CheckForWork reply checks. The disabled path returned ENOTSUP; the eight-core
MSDC regression passed. These results are recorded under ../build-audit/.
The GUI run is tracked separately; full physical acceptance remains outstanding.
