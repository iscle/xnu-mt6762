Recovery selection through the exact LK BCB consumer
===================================================

The dumped LK has an ordinary persistent boot-command consumer at0x48017e38.
It allocates6144bytes, calls its misc loader, copies the first1088bytes into its
legacy command/status/recovery structure, and compares the command at byte0
against ``boot-recovery`` and ``boot-fastboot``. Either exact match sets the
boot-mode global0x480af5cc to2, RECOVERY_BOOT, and returns true. Other commands
return false without changing the mode. This is distinct from fastboot's RTC
``reboot-recovery`` handler; neither route requires the other.

Exact storage placement and retention
------------------------------------

The misc loader at0x48003d08 resolves its partition-name literal to ``para``
(VA0x4805a3d4). The reader at0x48003c34 passes64-bit partition-relative offset0
and size6144 to ``partition_read`` at0x4803fcc4. There is no NAND page offset.
The command is therefore at byte0 of the GPT ``para`` partition, not at2048.
The standard command field is32bytes and must be NUL-terminated. The following
status/recovery/stage and other partition data are separate fields.

The consumer has no partition-write or clearing operation. Its heap read buffer
is freed, and the accepted command remains on storage. An XNU diagnostic does
not implement Android recovery's BCB clearing. A trial using this route therefore
needs an explicit restoration of the saved command field afterward, preserving
unrelated current ``para`` contents;
otherwise subsequent boots can repeatedly select the diagnostic recovery.
Neither restoring recovery alone nor a power cycle clears the BCB command.

No ``bootonce-bootloader`` literal exists in the exact LK. The exact consumer
rejects it in the offline test. ``boot-fastboot`` selects recovery here (for
userspace fastboot), not LK fastboot. It is not a substitute one-shot route to
the desired bootloader. A ``boot-bootloader`` substring in the image belongs to
the registered ``reboot-bootloader`` command and does not establish BCB support.

Scope of a separately authorized trial
-------------------------------------

A minimal boot-command change, after requiring a fresh empty baseline command,
would replace only the32-byte command field with
NUL-terminated ``boot-recovery`` and zero padding, preserving every byte after
that field. The current full partition must first be backed up/read back and
its GPT location/size independently verified. The parent's separately verified
GPT bounds are byte0x2108000 with length0x80000. A sector-based transport must
preserve the other480bytes of the first512-byte sector, and restoration must
preserve unrelated current fields rather than blindly replaying stale full
partition contents. This review does not supply a
write tool, marker image, device command, or new authorization. It does not
advise clearing arbitrary recovery arguments: existing fields can include OTA
or wipe instructions, which must be inspected privately before a trial and
must not be synthesized. The exact XNU diagnostic ignores Android recovery
arguments, but a fallback/restored stock recovery may not.

The normal boot initialization calls this consumer at0x480038e8. Earlier
boot-mode priorities can bypass it; notably the nearby cached reset-reason2
branch selects another route before calling it. Thus the consumer behavior is
proved, but an unobserved DA shutdown/reset state is not guaranteed to reach it.
A full verified readback of the installed candidate is still necessary after
an intervening Android boot.

Offline execution evidence
--------------------------

``audit_bcb.py`` executes the exact LK consumer, partition-name/offset wrapper
and libc copy/compare routines in Unicorn. Only allocation, logging/timer,
partition-existence query, partition-read transport and final free are modeled.
The transport asserts the request is precisely ``para``, offset0,6144bytes.
Four cases passed: boot-recovery and boot-fastboot select2; empty and
bootonce-bootloader select no recovery. Input bytes remain unchanged. Bounded
instruction ranges and results are in ``bcb-review-evidence.json``.

This is not a physical reset or recovery boot test. No phone action occurred::

  python3 tools/mt6762/physical/audit_bcb.py \
    --lk /path/to/lk.bin --output /tmp/bcb-review-evidence.json
