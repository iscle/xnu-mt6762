Recovery candidate independent review
=====================================

Candidate SHA256
``b57766a667c18e6ba854c81a24346c6582ad02fa31f89a93769c7086275c0005``
was checked against stock recovery SHA256
``470a453801aefddc83810f7b45647ecd581f1cd93a87ff51ab178561e82c2a15``.
Both are33554432bytes. Independent boot-v2 parsing confirms the stock base DTB
and recovery DTBO are byte-identical in the candidate; all declared components
fit the serialized image. The candidate's unsigned AVB metadata is512bytes at
offset6074368, with algorithm NONE and flags0. The producer separately ran
avbtool's hash verification; that integrity result is not trusted signing.

This route bypasses the specific fastboot cache omission
------------------------------------------------------

The exact stock LK normal loader selects recovery type1 and follows its AVB
loading path. After returned partition data is available,0x48049f94 allocates
its named cache,0x48049fb0 copies those loaded bytes, and0x48049fc2 calls the
same decapsulator which crashed in fastboot. The cache table aliases
``recovery`` and ``boot`` to the same entry. This supplies the cache that
``cmd_boot`` omitted. It is evidence that this specific NULL-cache failure is
avoided by successful normal recovery loading, not that all later boot stages
or XNU have been validated physically.

Unsigned verification and policy are separate
--------------------------------------------

The recovery branch sets slot-verification flag4 at0x48049e30. The exact slot
verifier selects requested-partition footer loading for that flag (the modern
NO_VBMETA_PARTITION behavior). Main vbmeta flags3 therefore are not sufficient
evidence that recovery accepts an unsigned image. Recovery's own footer and
unlocked-device authentication policy matter independently.

Unicorn executed the exact dumped LK ``avb_vbmeta_image_verify`` at0x48048bf0
with the candidate's actual512-byte metadata and no function mocks. It returned
1, OK_NOT_SIGNED. The exact caller's error-policy branch at0x480465e2 was then
executed with both boolean inputs: zero reaches error exit0x480464b4; one
continues at0x480465ec. This proves the unsigned result is conditionally
continuable, not unconditional acceptance.

The platform loader derives allow-error bit0 from its authentication-policy
result at0x48049dda..0x48049de4; that bit reaches the recovery call alongside
flag4. Supplied BSP ties this policy to security/unlock state. The exact current
physical recovery-policy return has not been observed, and this bounded review
does not replace it with an assumed success. Invalid metadata, allocation,
partition I/O or later boot failures remain possible even with allow-error set.
No new concrete packaging mismatch was found in the bounded checks.

Stock reboot-recovery route
--------------------------

The recovered static fastboot registration resolves ``reboot-recovery`` to
Thumb handler0x4801db91. It checks the RTC setter, calls0x4800839c with1,
sends fastboot OKAY, then calls reset0x48043274 with1 (bypass power-key behavior).
The exact RTC setter reads PMIC register0x5b4, preserves other bits, sets0x10,
writes it back and triggers RTC commit. This matches the supplied RTC recovery
marker. The handler does not boot Android first or issue a recovery-fastboot
command to the misc partition.

Thus an independently established DA-to-fastboot transition followed by this
stock handler can request recovery without an intentional intermediate Android
boot. The DA transition itself, successful RTC retention/reset, and actual
recovery selection are not exercised here. No phone command or partition write
was performed by this review, and a write requires the parent's separate user
authorization and backup/readback procedure.

Reproduction
------------

``audit_recovery.py`` reads only the pinned LK, stock recovery and candidate.
It validates the image structure and component equality, runs the exact verifier
and both unsigned-policy branches, and emits bounded instruction evidence::

  python3 tools/mt6762/physical/audit_recovery.py \
    --lk /path/to/lk.bin --stock /path/to/recovery-stock-before.bin \
    --candidate /path/to/recovery.img --output /tmp/recovery-review.json

It requires existing Capstone and Unicorn and emits no firmware bytes/private
logs. ``recovery-review-evidence.json`` records the completed checks. No full
AVB partition-I/O session, complete boot, framebuffer display or XNU execution
is claimed.
