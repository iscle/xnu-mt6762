Recovery candidate build1 validation
===================================

The exact33554432-byte recovery image, SHA256
``b57766a667c18e6ba854c81a24346c6582ad02fa31f89a93769c7086275c0005``,
passed the existing payload probe in three independent synthetic handoffs.
Headless execution reached the embedded PID1 and reported result1/cases205
twice, then DONE. The original static512MiB FDT caused no-window refusal before
XNU. The inherited-display fixture produced a captured screen directly
reviewed for READY, both result1/cases205/error0/size4 passes, and DONE. Display
register-write counters remained zero.

The probe loaded only the Image decompressed from this recovery image and its
image-derived runtime FDT. No separate kernel segments, boot arguments, Apple
device tree or userspace were loaded. XNU reported16KiB VM pages and4KiB
hardware pages. The embedded compressed kernel and ramdisk are byte-identical
to diagnostic boot build4; the base DTB table and recovery DTBO are
byte-identical to the inspected stock recovery backup.

Builder review and reproduction
-------------------------------

``build_recovery_trial.py`` checks the exact stock recovery digest and32MiB
size, pins the official AOSP avbtool bytes, compares base DTBs and load
addresses, and repacks using stock recovery metadata. The shared boot-v2
packer recalculates the Android image ID and recovery-DTBO offset. The builder
then checks that adding AVB metadata preserved the packed payload and stock
tree components. The generated footer describes an unsigned NONE vbmeta with
no authentication block. avbtool's verify operation confirms the footer and
SHA256 hash descriptor; it does not supply trusted signing.

An independent invocation of the same builder with the pinned inputs into
``boot/physical-recovery-build1/review-reproduction`` produced a byte-identical
image with the same SHA256. No defect was found in this inspected producer
path. The bounded source evidence is ``recovery-build1-probe-evidence.json``;
private run directories retain the full reports, UART logs, frame pixels,
screen PNG, and separate visual-review record.

Reproduction uses ``probe_payload.py`` exactly as documented in
``PAYLOAD-PROBE.rst``, with ``--image`` selecting this recovery.img and a new
output directory for each case. Use default options for headless, then
``--static-memory``, then ``--display-fixture --visible-console --seconds 5``.
The visible-console run deliberately
leaves its aggregate result pending separate screenshot review; its UART
observations are not treated as proof of visible text.

Limits
------

This probe extracts and boots the inner payload directly. It does not execute
LK's recovery loader, select a recovery slot, apply recovery DTBO overlays, or
enforce the actual device's AVB/recovery policy. The stock recovery DTBO is
preserved and hashed, but is not applied to the probe's FDT. Therefore these
passes do not establish physical recovery boot success or that the bootloader
will accept the unsigned image. No device operation was performed in this
validation task.
