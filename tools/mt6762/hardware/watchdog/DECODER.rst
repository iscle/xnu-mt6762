Trial record retrieval and decoding
===================================

``decode_trial.py`` reads local files only. It requires exactly128bytes and
validates magic/version, reserved fields, known flags, state-specific fields,
deadline bounds and timestamp ordering. An expiry must have a nonzero attempt
count, elapsed time at least the requested deadline and a last-feed gap within
the producer's10second guard (plus1ns rounding tolerance). State3's out-of-range
length flag must agree with the observed lengths. Such a flagged length is
reported as corrupt diagnostic data, never used to read additional memory.
State2 may contain partial flush metadata and is never called a completed clean.
There is no CRC or inverse-state pair in this producer ABI: these checks reject
detectable inconsistencies, but cannot establish that every plausible record
was atomically captured.

Raw observations
----------------

``decode_unbound(raw)`` returns validated raw observations with
``identity_bound=false`` and both attribution fields false, even for state3.
This is appropriate before provenance has been reviewed. CLI equivalent::

  python3 decode_trial.py trial.bin --unbound

Identity-bound observations
---------------------------

``decode_bound`` additionally requires the frozen stripped kernel, its unstripped
symbol artifact, physical Image manifest, raw256-byte loader trace, explicit
observed record PA and an externally SHA256-pinned binding document. The binding
document's closed schema is::

  {
    "format": 1,
    "kernel_sha256": "<64 lowercase hex>",
    "symbol_sha256": "<64 lowercase hex>",
    "image_sha256": "<64 lowercase hex>",
    "trace_identity": "<64 lowercase hex>",
    "symbol_va": 18446744005119186240,
    "physical_address": 3551663424
  }

The numeric values above are illustrative; derive both for the selected frozen
build. The independently pinned binding digest must come from the reviewed
capture configuration, not be calculated from whichever document arrived with
an unknown capture. The document is the external authority for the paired
stripped/unstripped artifacts. The decoder verifies their bytes against its
hashes; it DOES NOT reproduce stripping or prove that relationship on its own.
Its output explicitly includes ``strip_equivalence_verified_here=false``.

The decoder reads the actual defined ``_mt6762_trial_record`` symbol from the
unstripped Mach-O, skipping legitimate STABS debug duplicates. It requires the
record to fit its defining section and a writable segment. The stripped kernel
segments must match the selected Image manifest. Record PA is derived from
those segment offsets and the same-image loader trace's selected RAM base;
both the explicitly supplied PA and reviewed binding must match. The trace
must have the expected identity and a committed final branch marker. That
marker alone does not prove XNU execution; record state is separate evidence.

For frozen kernel53/Image38, the independently observed symbol VA is
0xfffffff007b21540 and the expected PA for RAMbase0xd0000000 is0xd3b21540.
Do not reuse these for a different kernel or relocation. CLI bound mode::

  python3 decode_trial.py trial.bin \
    --kernel /private/kernel.macho --symbols /private/kernel.unstripped \
    --manifest /private/physical-manifest.json --trace /private/trace.bin \
    --physical-address 0xd3b21540 --binding /private/trial-binding.json \
    --binding-sha256 <independently-reviewed-digest>

This attributes a plausible expiry/cache-clean observation to the selected
Image, not uniquely to one boot of that Image. The trial record has no per-boot
nonce; host capture ordering and independently checked loader linkage remain
required. State3 means cache-clean instructions completed. Every result retains
``reset_proven=false``, ``dram_retention_guaranteed=false`` and
``coherent_log_snapshot=false``. Do not upgrade these based on a valid decoder
result alone.

Validation: ``python3 test_decode_trial.py`` covers all states, truncation,
magic/version/reserved/flag errors, deadline and timestamp inconsistencies,
length diagnostics, valid reviewed binding, stale trace identity, wrong
kernel/symbol artifact, wrong PA and mismatched load segments. Actual frozen
kernel53 symbol extraction and Image38 relocation were also checked locally
with synthetic trace/disabled-record bytes; that was not a physical capture.
