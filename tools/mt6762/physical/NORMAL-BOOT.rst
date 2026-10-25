Normal boot diagnostic packaging
================================

build_normal_trial.py packages the already frozen Image5 diagnostic into the
exact32MiB normal ``boot`` partition layout. It does not rebuild XNU, modify
Apple userspace, change the loader trace, access a phone, reset a device or
restore a partition. Keep the verified complete stock boot backup for recovery
if needed; there is no automatic restoration step.

Inputs are pinned: the full stock boot backup, complete Image5 Android
container, official AOSP avbtool and the previously captured main vbmeta with
flags3. The capture is offline evidence, not proof of the phone's current
state. Current unlocked state, current main-vbmeta flags and any installation
must be checked by the parent device workflow independently.

The stock boot footer identifies partition ``boot`` and has an RSA2048
signature. That signature cannot authenticate a changed payload. The new image
instead carries an unsigned ``NONE`` AVB header, exactly one SHA256 hash
descriptor named ``boot``, and a footer spanning the full partition. This is
an integrity descriptor, not trusted signing or a bypass claim. Acceptance by
the actual normal boot path depends on its unlocked/verification policy and
remains physically unproved by packaging or QEMU.

The producer preserves the stock boot-v2 header metadata, addresses, DTB and
other non-diagnostic components, and verifies the repacked payload equals the
original Image5 container byte for byte before adding the footer. The compressed
Image, embedded diagnostic PID1, kernel23, trace identity and16KiB VM/4KiB
hardware-page configuration are unchanged. No recovery image is relabeled as
boot: the template and descriptor name are independently fixed to stock boot.

Independent validation checks partition size, footer bounds/version, unsigned
header/key/authentication fields, a single bounded descriptor, exact partition
name, payload size, salt and recomputed SHA256. Official ``info_image`` and
``verify_image`` must also pass. Zero-length key fields may legitimately retain
bounded nonzero offsets; those are checked by size and bounds, not mistaken
for actual key material.

Reproduction, offline::

  python3 tools/mt6762/physical/build_normal_trial.py \
    --diagnostic /path/to/physical-xnu-build5/mt6762-xnu-diagnostic-boot.img \
    --boot-backup /path/to/complete-stock-boot.bin \
    --vbmeta-capture /path/to/inspected-main-vbmeta-flags3.bin \
    --avbtool /path/to/pinned-avbtool.py --out /new/output/directory

The first producer validation attempt incorrectly required all empty key
offsets to be zero. That refusal and its candidate were retained under
physical-normal-build1-initial-validation-failed. The corrected checks passed
for build1. A subsequent documentation-only policy correction removed an
automatic stock-restoration instruction and parenthesized descriptor-size
arithmetic; build2 was freshly generated to preserve honest source provenance.
Build1 and build2 contain identical full image bytes, with SHA256
``0b3f8f438e9bca7299a845ab663a9553e0209ddeaaf717fc86cd056e280b09ef``.
Use build2's manifest for the current producer; build1's original manifest is
retained as historical evidence.

Six AVB tests passed, including wrong partition name/digest, bounded metadata,
flags/authentication, size/truncation, payload changes despite a valid Android
image ID, and the actual avbtool-produced candidate. Exact-image QEMU execution
of build1 reached the unchanged diagnostic PID1 with result1/cases205, printed
16KiB VM/4KiB hardware pages and retained trace phase10. Build2 is byte-identical,
so that execution evidence applies to its payload without claiming a second
run. QEMU bypasses the physical LK verification/normal-path routing and does not
prove either; trace phase10 alone also does not prove XNU execution.
