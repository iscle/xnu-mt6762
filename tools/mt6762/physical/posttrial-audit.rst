Temporary boot trial: retained LK failure
========================================

The complete20MiB expdb capture establishes that the downloaded image did not
reach XNU. At file offset0x13425a0, LK receives fastboot ``boot`` at14905ms,
with a0x5bf000-byte image downloaded at0x48b00000. At0x134267b it reports
``boot image is NULL``; at0x1342697 it panics with caller0x4801dee3 and
``boot image decapsulate fail!``. The next retained boot reports ``rst from: lk``,
boot reason4, WDT status0x6 and exception type0x6. This failure precedes Linux
Image decompression and the transfer to the diagnostic loader. It is not an
observed XNU panic or evidence of an XNU storage write.

Exact shipped-LK explanation
----------------------------

The fastboot handler beginning0x4801deb4 saves its downloaded-data argument in
r7, allocates/copies a0x67c-byte header, and passes r7 in r0 to0x48036f38.
The return address is0x4801dee3, matching the retained panic.

The callee does not retain or inspect that incoming r0. It immediately loads
literal ``boot`` into r0, looks up an image through0x48037d24, and saves the
result in r4. It also performs ``vendor_boot`` lookups. The lookup routine
returns a cached record's pointer at offset0xc, or zero. A zero boot image
branches from0x48036f62 to0x48037270, prints the observed NULL message, then
calls panic through0x480371bc with the saved caller return address. Selected
instructions and hashes are retained in ``posttrial-evidence.json``.

This is a shipped fastboot caller/decapsulator interface mismatch: the caller
provides downloaded bytes but the callee requires an already populated image
cache. The supplied older BSP ``sys_commands.c:611`` still calls
``load_bootinfo_bootimg(data)`` and its ``boot_info.c`` takes that pointer; the
exact binary has newer boot/vendor_boot cache behavior. Source comments alone
would miss this difference. Changing the download's boot-header fields cannot
populate the missing cache through this observed path. No alternate command,
patch, or workaround has been tested or implemented by this audit.

Persisted corruption warning is separate
---------------------------------------

The complete8MiB seccfg images after unlock and after the trial differ in only
61bytes, all within0x240..0x282. Their first512bytes, including unlock state3,
are identical. The changed area is not the unlock header. The persistent
container at0x200 has magic0x90790922; its newly added big-endian descriptor at
0x240 has tag0x90790804, a23-byte ``avb.managed_verity_mode`` key, and a32-byte
value. Values are not published; source metadata suffices for this conclusion.

The supplied LK libavb records an OS vbmeta digest under that key when its
restart-caused-by-hashtree-corruption flag is set. It retains EIO mode while the
OS digest matches. The platform dm-verity handler displays the corruption
screen for EIO mode and, in the supplied configuration, powers off after5s
unless the power key is detected. This explains why a warning can persist even
when the vbmeta partition itself remains unchanged. The parent separately
verified the complete32MiB boot partition and8MiB vbmeta against the original
dump; this audit does not replace that independent comparison.

The first log-only audit did not establish the cause of the corruption status.
The subsequent exact-schema analysis in ``lk-runtime-audit.rst`` identifies
header offset0x10 as this LK's dm-verity status and shows it changed0 to1 during
unlock, before the temporary boot. Neither the persistent record nor the failed
fastboot command identifies a damaged system block. Later retained stock-Linux
startup reports a latched EMI MPU read
violation at0x47d81b80, in the reserved ATF range; it occurs in a separate normal
boot and is not evidence that XNU executed. These distinctions must survive
any recovery narrative.

Coverage and reproduction
-------------------------

The first expdb capture was only8MiB and omitted the relevant LK logs. The
complete capture is20971520bytes, SHA256
``febda44f4e7455617a127617c6bc4013dd13e4027f16e558416247a977de6cbc``.
The script scans that complete artifact but emits only allowlisted boot-event
messages and bounded LK code ranges, with hashes. It does not publish command
lines, device identifiers, full logs, or persistent-value bytes. No phone access
or filesystem/partition mutation is performed::

  python3 tools/mt6762/physical/audit_posttrial.py \
    --trial /path/to/mtk-unlock-20261024 \
    --dump /path/to/mini_iphone_dump_2 \
    --bsp /path/to/workspace \
    --output /tmp/posttrial-evidence.json

The exact captured expdb/LK hashes are required. Capstone provides the established
format-aware fallback because the REA firmware/native provider was unavailable.
No native kernel or boot payload source was changed during this investigation.
