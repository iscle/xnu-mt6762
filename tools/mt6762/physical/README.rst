Temporary physical XNU diagnostic
=================================

Physical trial status: the dumped LK's fastboot boot path panics before XNU
entry. Its caller passes the download pointer to a routine that instead looks
up an absent cached boot image. The retained log says ``boot image is NULL``
and ``boot image decapsulate fail!``. See posttrial-audit.rst. Header changes
alone cannot fix that interface mismatch; the candidate is not a working
temporary boot route on this stock bootloader. Do not flash this boot image as
a workaround. RECOVERY-TRIAL.rst describes a separately packaged recovery
candidate, the authorized installation and the user's instruction to retain it.
The next selected route is the normal boot partition, authorized by the user;
see NORMAL-BOOT.rst for its prepared image and validation. Early transient
BootROM USB enumeration alone does not establish a boot-routing failure.

This directory builds a self-contained Android boot-v2 image for a temporary
``fastboot boot`` trial on the inspected A25/MT6762 phone. It contains XNU and
a small project-built PID1 observer, not a full iOS installation. The selected
Apple userspace binaries are not rebuilt or included here. The full iOS system
RAM disk exceeds this bootloader's128MiB download limit.

The diagnostic boots one CPU with16KiB VM pages over4KiB hardware translations
and requests the205-case generated DriverKit RPC selftest. It supplies no native
peripheral ownership handoff. Touch, charging, buttons, DMA, DVFS, and the iOS
GUI are not enabled or accepted by this trial. USB ADB is unavailable in XNU.

Build without accessing the phone
--------------------------------

From the XNU root, with explicit local input paths and a new output directory::

    python3 tools/mt6762/physical/build_payload.py \
      --kernel /path/to/kernel.macho \
      --diagnostic /path/to/iig_probe.macho \
      --template /path/to/stock/boot.bin \
      --llvm /path/to/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin \
      --out /path/to/new-candidate

The template's addresses, stock DTB table and64-bit bootopt are preserved.
The old AVB trailer is omitted; the resulting image is unsigned. The manifest
records the kernel, diagnostic, template, loader dependencies, tools and image
hashes. No binary or firmware is committed to this repository.

The physical Image enters at0x40080000 with the bootloader's runtime FDT in x0.
It admits a little-endian, MMU/data-cache-off Cortex-A53 at EL1 or EL2 and a
13MHz counter. EL1 entry preserves the existing GZ hypervisor state. EL2 entry
follows the supplied Linux entry setup before dropping to EL1. The entry path
has a private64KiB stack, bounded UART output and a fatal exception vector.
Freestanding compilation uses -mstrict-align because MMU-off Device semantics
prohibit unaligned accesses, and -ffixed-x28 reserves the fatal-vector guard.

The bounded FDT parser requires the supported board identity and actual memory
map. It excludes firmware reservations, possible dynamic allocation ranges,
the entire source Image/stack, framebuffer and FDT before selecting a512MiB
window below4GiB. The static512MiB placeholder map fails admission. There is
no guessed-address fallback. Kernel segments and the embedded RAM disk, ADT
and boot arguments are copied and relocated only after admission.

Screen diagnostics
------------------

The videolfb tag is only a candidate. Display writes additionally require an
independent exact memreserve/reg reservation inside RAM, matching live power,
clock gates, single-layer OVL, RDMA and DSI readback, and the inspected
384x854/1536-byte BGRA layout. Possible allocation constraints cannot authorize
the framebuffer. The loader reads these display registers but does not write
them. On acceptance, it prints progress and requests XNU's text console on
the inherited framebuffer. A guard-page/canary host test bounds the renderer.
On verified video the loader selects serial=0 so /dev/console remains visible
through PID1; otherwise serial=3 retains the UART diagnostic path. This avoids
switching a working screen console to an unavailable UART during initialization.

With no UART and an unverified framebuffer, a failed boot may show no new text.
An unchanged logo, black screen, or later reboot is not proof that XNU started.
No storage log is written. The AP watchdog is neither fed nor disabled; the
stock code programs a30-second interval, but exact reset timing and routing
remain unverified. This is a short diagnostic, not a usable phone environment.

Validation
----------

Run the host suite from the XNU root::

    python3 -m unittest discover -s tools/mt6762/physical -p 'test_*.py'

probe_payload.py unpacks the exact delivered image and boots only its raw Image
and a separately identified synthetic runtime FDT under the local MT6762 QEMU.
No external kernel segments, ADT, boot arguments or userspace are supplied.
It discovers register indices from GDB XML, reproduces the LK PC/x0 handoff,
and records results. --static-memory checks refusal of the stock placeholder;
--display-fixture checks a synthetic inherited scanout. These are emulator
tests, not bootloader authentication or physical display validation.

Historical temporary command (fails on this LK)
----------------------------------------------

The attempted command was::

    fastboot boot /path/to/new-candidate/mt6762-xnu-diagnostic-boot.img

Do not repeat it unchanged on the inspected LK: the retained failure occurs
before payload entry. A successful transfer alone does not establish XNU
execution. Visible XNU text or the PID1 selftest result is separate evidence.
The host probe never runs this device command. The offline LK cache bridge is
not yet deployable; its runtime placement and transport remain unverified.
