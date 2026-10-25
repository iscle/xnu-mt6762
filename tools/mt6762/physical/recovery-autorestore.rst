Stock Android recovery restoration attempt
==========================================

Read-only extraction of the exact supplied ``super.bin`` finds a restoration
service in vendor. Both LP geometry/header/table checksums were validated before
extracting only system and vendor into a private evidence directory. No Android
file was changed and no device command was issued.

Exact files and behavior
------------------------

Vendor ``/etc/init/vendor_flash_recovery.rc`` (89bytes, SHA256
``d5ac2dc095118cb143443992bdffe2e9925f663efc85120ced1225d5c43218d7``)
defines ``vendor_flash_recovery`` running ``/vendor/bin/install-recovery.sh``,
class main, oneshot, without disabled. The system ``/system/etc/init/hw/init.rc``
starts class main on nonencrypted startup and framework-start decrypt events.
The shell script (685bytes, SHA256
``cc62d106bfc0c2716e2c081e4f4df8670cf93193ffa4286fc199914f732d52dd``)
checks the entire33554432-byte recovery partition and, on mismatch, invokes
applypatch using the boot partition and ``/vendor/recovery-from-boot.p``.
The patch exists (7345447bytes, SHA256
``f4522e79d3f452979bb5b2353f4b1732c9ed994a9ed06474cfc136faac4da74f``).
Partition paths append ``ro.boot.slot_suffix``; this is ordinary stock behavior.

The script's required recovery SHA1 is
``a78cf51d20a9fb0d405e41ef50211af07ff52bbd``; its source boot SHA1 is
``eb7092b92f8921f9a4eb8d1d42907dd72f9d3f89``. Neither matches the saved exact
stock partitions: stock recovery SHA1 is
``dbdef42f85b53b3d810edd7ae1fbd2b3dd903bb0`` and stock boot SHA1 is
``ea090eb65dd5f08fb5bbc213ad89932c75f9934a``. The diagnostic candidate also
fails the expected recovery hash, so it triggers an attempt if this service runs.

Consequently Android startup has an enabled automatic restoration **attempt**,
but successful overwriting is not established. The source-hash mismatch can
prevent patching; no successful current applypatch log or current partition
readback was obtained in this offline task. The prior candidate readback before
Android startup must not be presented as proof the candidate remains installed.
Conversely, this service's existence alone must not be described as proof it
was overwritten. A fresh recovery readback resolves the uncertainty.

Private evidence and extraction provenance
-----------------------------------------

Local evidence is under ``hardware/recovery-restoration-audit``: extraction
metadata, the four selected files, and findings.json. These firmware files and
full partition images are not source-package artifacts. System occupies
3790088sectors at super sector2551808; vendor occupies1596536sectors at sector
6342656 (512-byte sectors). The extracted images have SHA256:

* system: ``171ce3626a37eab8e66584cf2ba5c5bc132965b3d4eef93fa9b1169fb108c194``
* vendor: ``a37a00f26f0db7256d5254893474fc80e7f3cceaf94beac390754b0ed008ae53``

The files were read using ``debugfs`` without its write option. Product and
userdata were not extracted or searched. The initial inference of likely
restoration was explicitly narrowed after checking the mismatching SHA1 values.
