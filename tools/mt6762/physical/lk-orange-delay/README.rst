Exact-stock LK orange-state delay removal
========================================

This offline producer patches the phone's MediaTek Little Kernel (LK). The
complete 1 MiB candidate is kept privately as ``lk-orange-no-delay.bin``.
The producer has no transport, flashing, reboot or security-policy operations.
SHA256: 8b94cdf939ee6318c5d47b8e4feacef2d3ea0a3b1d37f292752bd6d4875c6849.

Only four bytes change: file 0x37b9a..0x37b9d, runtime 0x4803799a,
``0b f0 77 f8`` (Thumb BL 0x48042a8c) becomes ``00 bf 00 bf`` (two NOPs).
The immediately preceding MOVW passes 5000. Its target branches to the timer
conversion/wait routine at 0x48042a70. The exact warning function at
0x48037964 prints the orange heading, unlocked warning and original countdown
wording, refreshes the watchdog, waits, refreshes the watchdog and returns 0.
The patch removes only the wait call. It deliberately retains the original
"5 seconds" text; its display duration is no longer promised by that wording.

The exact dispatcher at 0x48037a84 compares state 2 and tail-branches to the
orange function. States 1 and 3 take the separate warning path; other states
return zero. All dispatcher bytes, strings, unlock/verification logic and other
delays remain byte-identical. Selected BSP vboot_state.c lines128 onward and
vboot_state.h corroborate orange state2 and mdelay(5000). The binary is the
patch authority, not a presumed identical BSP build.

Validation
----------

``test-report.json`` records Unicorn execution of the exact original/patched
functions for dispatcher states0..4 and direct orange entry. Orange loses
exactly one delay(5000), retains all3 prints and both watchdog calls. Other
paths, return values, SP and r4..r11 remain equal; external-call stacks are
8-byte aligned. Four malformed/unpinned input variants are rejected. Capstone
checks the old BL target and two replacement NOPs. Display, watchdog and timer
callees are mocked; this is not a full LK boot or physical timing test.

Reproduce in this directory (Python3 with Capstone and Unicorn)::

  python3 patch.py --stock /path/to/lk.bin --output /new/lk-patched.bin --report /new/patch.json
  python3 test_patch.py --stock /path/to/lk.bin --candidate /new/lk-patched.bin --report /new/test.json
  python3 audit.py --stock /path/to/lk.bin --bsp /path/to/workspace --captured /path/to/lk-capture --output /new/evidence.json

The builder refuses an existing output and any stock hash other than
5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a.
No instruction, blob or executable address is appended.

Container, installed slots and authentication boundary
------------------------------------------------------

The exact MediaTek header has magic0x58881688, payload length0xac5bc,
name lk, and extended header size0x200. The replacement lies inside the
existing declared payload [0x200,0xac7bc). Every header, embedded DT, trailer
and all bytes outside the call remain unchanged. This does not recompute or
invalidate-check any signature/hash covering the modified payload.

Parent's read-only current captures, independently checked here, show both
installed slots match the pinned original. GPT header/entry-array CRCs pass:
primary lk at0x1c400000, secondary lk2 at0x1c500000, each0x100000 bytes.
Both GPT attribute words are zero. BSP mt6765 main.c bldr_load_part_lk selects
lk2 only when lk active==0 and lk2 active>0; otherwise it selects lk.
part_common.c extracts the legacy BIOS bootable attribute. Thus BSP semantics
with this GPT select primary lk. This audit has not replayed the exact running
preloader's selector, and does not promise automatic fallback to stock lk2.
Keeping the secondary stock is a backup, not an established recovery policy.

BSP mt6765 partition.c part_load obtains get_vfy_policy, conditionally calls
sec_img_auth_init, loads declared dsize after the header, then conditionally
calls sec_img_auth. The precise compiled/fused authentication policy of the
installed preloader remains unresolved. The bounded exact preloader string
check found none of its expected LK-loading/auth log literals, so source
policy cannot be promoted to exact binary proof. Successful unsigned/patched
DA upload through BootROM is a different path and does not establish that
normal preloader loading will accept a modified LK. The candidate changes no
policy, certificate, signature or anti-rollback data, and its initial static audit did not establish normal-boot acceptance.

Evidence inventory
------------------

``patch-report.json``: full hashes and every changed byte.
``evidence.json``: bounded exact disassembly, BSP source hashes, current slot
hashes and GPT checks. ``test-report.json``: path/ABI replay results.
The patched proprietary image is local/private; no publication is implied.

Installation on 2026-10-25
--------------------------

The parent installed this candidate into primary LK using the existing download
agent session. Full readback equals the candidate. GPT, LK2, boot, para, seccfg
and vbmeta were read back unchanged; ``installation.json`` records their hashes.
The original full LK is retained privately. The installer permits one exact
primary-slot extent and stops on write, readback or preserved-region mismatch.
Its offline fault-injection checks passed. No reset was issued by the installer.
After a normal power-button restart, the retained LK function at 0x48037964
matches all 68 bytes of the patched function, including both NOPs. The fresh
XNU log has both successful diagnostic rounds (205 cases each). Primary LK
still reads back as patched; LK2 remains stock. This proves normal loading of
the patched image and continued XNU bring-up. Direct observation of the
warning duration remains pending; retained code is not an instruction trace.
