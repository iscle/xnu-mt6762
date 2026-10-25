Recovery-path diagnostic candidate
==================================

The shipped LK fastboot download handler fails before entering XNU; see
posttrial-audit.rst. Repacking the same kernel for the recovery partition is a
different boot route. It requires a persistent partition write followed by
restoration, even for a single trial. It is not a RAM-only fastboot boot image.
The user subsequently authorized the recovery trial and restoration. Build1
was written on 2026-10-24 and its complete32MiB readback matched the candidate.
The authenticated unlocked state and complete seccfg contents were preserved;
dm-verity status was0. The DA acknowledged a mode2 fastboot request, but USB
did not enumerate within30 polls and the user reported a black screen. Physical
XNU entry is not established. After the user pressed Power, Android booted
normally and ADB returned with flash.locked=0. No recovery reboot command had
yet been issued. Current recovery contents after Android startup have not been
read back, so automatic restoration cannot yet be excluded. Stock recovery
restoration remains mandatory; see recovery-trial-install-evidence.json and
the in-progress private record hardware/recovery-trial-20261024.

On2026-10-25 a new full readback found build1 still on recovery and the repaired
seccfg unchanged. Para contained the exact unsupported ``bootonce-bootloader``
command and empty recovery arguments. The approved direct trial replaced only
that32-byte command with ``boot-recovery`` and verified the entire para and
recovery partitions afterward. Security state remained unchanged. After a
normal DA reset the user reported a black screen; physical XNU execution is
not established. Post-trial log capture and stock recovery/command restoration
are pending the next download-agent connection. See recovery-direct-evidence.json.

Build locally, without device access::

  python3 tools/mt6762/physical/build_recovery_trial.py \
    --diagnostic /path/to/physical-xnu-build4/mt6762-xnu-diagnostic-boot.img \
    --recovery-backup /path/to/recovery-stock-before.bin \
    --avbtool /path/to/pinned/avbtool.py \
    --out /path/to/new-recovery-candidate

The producer requires the exact inspected 32MiB stock recovery backup and the
official AOSP avbtool at commit 761178607206f4cb2af79ed9eec52d8cbd814adb,
SHA256 e5a664a38db623da00f080219bc0ee60a640a9dc4a872803616fae4938ac749b.
The source is platform/external/avb on android.googlesource.com. No downloaded
tool, Apple binary, firmware or private device capture is included here.

Candidate build1 SHA256:
``b57766a667c18e6ba854c81a24346c6582ad02fa31f89a93769c7086275c0005``.
Stock recovery backup SHA256:
``470a453801aefddc83810f7b45647ecd581f1cd93a87ff51ab178561e82c2a15``.
Both are exactly 33554432 bytes. The backup was freshly read through the DA
and independently matches the original firmware dump.

The kernel and diagnostic PID1 are byte-identical to diagnostic build4. All
load addresses, the stock base DTB and recovery DTBO are retained. The producer
updates component sizes, recovery-DTBO offset and Android image ID, and adds a
fresh unsigned AVB hash descriptor/footer. Algorithm NONE supplies a checkable
container, not a trusted signature. Physical acceptance by the unlocked LK is
unverified. avbtool verify_image accepts the complete candidate's footer,
metadata and recovery hash. A negative check flipped kernel byte at image
offset2148 in a disposable copy; verify_image rejected the digest with exit1.
The diagnostic retains the limits in README.rst:
one CPU, 16KiB VM pages over 4KiB translations, no native peripheral ownership,
no USB ADB, and no full iOS userspace. A screen result depends on admitting the
actual inherited framebuffer. The stock watchdog remains running.

Controlled trial and restoration plan
------------------------------------

Before writing, obtain approval for replacing recovery temporarily and restoring
it afterward. Verify the candidate and backup hashes again, the device identity,
unlocked state and exact live recovery GPT extent. Read recovery again and
require equality to the backup. Stop on any mismatch.

Write only recovery using the existing reviewed DA path. Read back the complete
32MiB partition and require equality to the candidate before resetting. The
planned transition is DA shutdown mode2 (fastboot), followed by the stock
fastboot reboot-recovery command. Confirm fastboot enumeration before issuing
that command; do not intentionally boot Android between writing and the trial.
The exact RTC marker route is reviewed in recovery-review.rst; the DA transition
and physical recovery verification policy remain untested. Record visible
diagnostic text; an unchanged
logo or reboot alone does not establish XNU execution. No other firmware
partition or verification setting is part of this trial.

After success or failure, reconnect the established DA, restore the complete
original recovery backup, then read back all 32MiB and require its original
hash before returning to Android. If the readback differs, retain the DA
session and investigate before reset. Keep both local backup copies available
throughout. An automatic stock-recovery restoration during Android startup
must also be detected by readback; it is not proof the candidate ran.

Emulator checks execute the exact embedded raw Image with a synthetic runtime
FDT. They do not execute LK, its authentication policy or recovery DTBO merging.
Physical XNU entry, display, touch, charging and buttons remain unaccepted.
