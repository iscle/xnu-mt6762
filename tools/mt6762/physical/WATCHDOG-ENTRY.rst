Exact LK watchdog state on the kernel path
=========================================

The retained LK explicitly enables the AP watchdog during its early platform
initialization. The normal recovery-to-kernel path later writes a nominal
30-second interval and restarts the counter. These are exact binary findings,
not a physical observation of successful reset or entry into XNU.

Artifact and method
-------------------

``audit_lk_watchdog.py`` accepts only LK SHA-256
5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a.
The partition header is 512 bytes; runtime address is file offset +0x47fffe00.
Capstone extracts bounded Thumb ranges. Unicorn executes the original init,
length and restart instructions against plain RAM/MMIO, intercepting only the
logging function. No phone transport, reset, patch or boot command is present.
REA firmware inspection was unavailable because its caller-supplied Binwalk
provider was absent; this evidence comes from the stated local fallback.

Reproduce with the existing Python capstone/unicorn dependencies::

  python3 audit_lk_watchdog.py --lk /path/to/lk.bin \
    --output /private/lk-watchdog-evidence.json

The public ``lk-watchdog-evidence.json`` retains bounded disassembly and twelve
passing executions: initial MODE 0,0x64,0x7d crossed with NONRST2 selector 0,2,3,4.
No firmware blobs or private device identifiers are included.

Exact enable, disable and final interval
---------------------------------------

* Early platform call 0x48002b98 invokes init 0x48043130. Init first clears MODE
  mask 0x4f and ORs 0x22000010, writes an initial 10-second length 0x5008, then at
  0x480431dc..0x480431ec reads MODE, clears bit1, ORs 0x22000000|0x5d and writes
  MODE 0x10007000. It finally writes RESTART 0x1971 at 0x10007008. The enable bit0
  is set regardless of its initial value. With modeled initialMODE 0x64, the
  two MODE writes are 0x22000030 and0x2200007d. Bit 5 is preserved rather than
  independently established.
* The bounded scan of aligned Thumb BL/B.W candidates from file 0x200..0x80000
  finds one direct call to the disable routine: 0x4800332e→0x48042f38.
  The exact surrounding path tests boot_arg + 4 against 0x64 at 0x4800302a..3030,
  the DOWNLOAD_BOOT selector. It disables watchdog, performs platform/cache/MMU
  cleanup and calls jump_da 0x48016d98 with the retained da_info fields. This is
  separate from the normal recovery kernel handoff. The boot-mode enum 0x64 and
  a watchdog MODE value 0x64 are unrelated fields despite their equal numeral.
* On the final boot_linux path,0x4801bbca loads argument 30;0x4801bbcc calls
  0x48042f50, whose exact code writes (30<<11)|8 = 0xf008 to LENGTH 0x10007004.
  The following call 0x4801bbd0→0x48042f6c writes RESTART 0x1971. Neither routine
  clears MODE enable. The selected BSP's seconds-to-length formula and register
  definitions corroborate these exact instructions; the conclusion does not
  depend on a generic BSP enable setting.

Timing and remaining uncertainty
-------------------------------

A fresh LK boot that reaches this normal init and recovery handoff therefore
programs an enabled watchdog before kernel entry. The current DA's disabled
MODE 0x64 is not a reason to assume it remains disabled after that fresh path.
This is conditional on executing the path, not proof that a reset operation
actually reached it. A DA jump, an early LK failure, or a different continuation
has different implications.

The programmed interval is nominally 30 seconds from the last restart, not
necessarily 30 seconds from a host command or even from XNU entry. MODE contains
IRQ bit 3 and dual-mode bit 6; inherited IRQ-level bit 5, GZ/ATF interrupt routing,
later firmware writes or watchdog feeding, hardware clock/acceptance and PMIC
watchdog behavior are not established here. The direct-call scan cannot rule
out indirect calls, ARM veneers, secure-world writes or alternate paths.
Neither a precise 30-second nor a precise 60-second physical reset is proved.
No automatic reset observed by a deadline would not by itself distinguish
missing kernel entry, secure handling, timer failure or a different boot path.
The diagnostic preserves watchdog policy and must not claim an indefinite
session or silently add feeding/disabling as a substitute for this uncertainty.
