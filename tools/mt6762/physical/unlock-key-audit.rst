Exact LK unlock confirmation audit
=================================

Scope and outcome
-----------------

This is read-only analysis of the supplied LK and device trees, cross-checked
against the supplied BSP. It performs no phone commands, unlock operation,
patching or bypass. The exact artifact SHA256 and six bounded, fully decoded
Thumb ranges are in ``unlock-key-evidence.json``. The REA native/firmware provider
was unavailable in this session; Capstone and the existing format-aware FDT
parser provide the reproducible fallback. No proprietary binary is packaged.

The LK confirmation prompt says Volume Up, but its actual unlock loop passes
**hardware key17** to the key detector. Key17 is routed to the **PMIC HOME/reset
input**, whereas the supplied keypad overlay maps Volume Up to keypad key1.
This is a concrete code/configuration mismatch; it is not evidence that any
particular physical button on this phone reaches PMIC HOME. Android's recorded
Volume Up/Down events establish those Android inputs work, not that LK uses them
for confirmation.

Separately, the recorded OEM unlock ability is0. Enabling OEM unlocking through
Android's normal setting addresses that permission barrier. It does not change
the observed LK confirmation selector. Do not describe a repeated Volume Up
attempt as a verified solution, and do not guess a physical HOME button mapping.

Exact control flow
------------------

* ``0x4802636c`` enters the unlock routine and calls the prompt renderer.
* ``0x48026398`` loads17; ``0x4802639a`` calls key detection at
  ``0x48004aec``. A false result checks the factory/cancel key from the DT
  structure's ``+0x13c`` field, then loops. There is no timeout or delay in this
  polling loop.
* A true confirmation sends ``Start unlock flow`` through ``fastboot_info`` at
  ``0x480263a6`` before querying unlock permission at ``0x480263ac``. Denied
  permission returns fastboot FAIL after the on-screen failure and3s delay.
* Cancellation at ``0x4802641c`` prints return-to-fastboot, delays3000ms,
  restores the menu and calls **fastboot_okay** at ``0x48026434`` without
  entering the confirmation branch.
* The successful path separately displays Unlock Pass, delays3000ms and calls
  fastboot_okay at ``0x48026490``.

The first recorded request returned only ``OKAY [18.758s]``, without Start
unlock flow, and the subsequent query still reported ``unlocked: no``. This is
consistent with cancellation, including time spent waiting for a key, rather
than a timeout or successful unlock. The exact user action producing cancellation
was not observed. Host OKAY alone is insufficient evidence of unlocked state.
The later permission query reports ``unlock_ability = 0``; neither result proves
that the confirmation branch was reached.

Key routing and artifact boundaries
-----------------------------------

The exact detector first compares against hardware power and reset keys loaded
from its DT structure. Reset key17 takes ``pmic_detect_homekey`` at
``0x4800788c``; it reads PMIC register0x24, mask1, shift3, and treats zero as
pressed. Power key8 reads the same register's bit1. Other keys read active-low
keypad bits from ``0x10010004 + 4*(key/16)``. The confirmation therefore does not
read the normal keypad bit for Volume Up in this configuration.

The DTBO keypad fragment74 supplies hardware power8, reset17, recovery1 and
factory0. Its keypad map has index0 = Linux KEY_VOLUMEDOWN114 and index1 =
KEY_VOLUMEUP115. Exact LK fallback values also use power8/reset17/factory0;
its recovery fallback is17. The embedded FDT at LK file offset0xad850 is
byte-identical to extracted ``boot.bin.dtb`` (109716bytes,
SHA256 ``658e181d1a13d930dc09567883e734bdbd4579350c8332ff954a0ecbb2ed08fe``)
and has none of these keypad properties. The current physical boot's overlay
application was not read back. Both supplied overlay and fallback route17 to
PMIC HOME, so that uncertainty does not make key1 the hardcoded confirmation.

The BSP ``sec_unlock.c:337`` mirrors the observed poll and cancel-OKAY behavior.
Its comments label confirmation Volume Up. The target ``cust_key.h`` defines
``MT65XX_MENU_SELECT_KEY`` through ``MT65XX_BOOT_MENU_KEY``, with fallback17
when the recovery-key macro is absent. Exact binary evidence establishes the
compiled constant; the original vendor build's macro configuration is not
available. The source comment does not override the actual constant.

Bounded next observations
-------------------------

Use the normal OEM unlocking UI for the independent permission prerequisite.
Any further authorized unlock attempt needs the actual prompt text and observed
key response, and an unlocked-state query afterward. There is no supported
software retry or physical alternative key established by this audit. Do not
infer that a touchscreen home gesture, power key or unobserved button chord
reaches PMIC HOME, and do not patch the confirmation check to conceal the
mismatch. No security permission or key-register writes are part of this work.

Reproduction
------------

Run from the XNU source tree with the existing extracted firmware directory::

  python3 tools/mt6762/physical/audit_unlock_keys.py \
    --dump /path/to/mini_iphone_dump_2 \
    --firmware /path/to/firmware \
    --bsp /path/to/workspace \
    --output /tmp/unlock-key-evidence.json

Optional ``--trial /path/to/temporary-xnu-trial-20261024`` includes only the
three named command-result outputs and hashes, excluding command arguments and
device serials. Source files are hashed rather than copied. The parser rejects
an unexpected LK hash or incomplete instruction-range decoding.
