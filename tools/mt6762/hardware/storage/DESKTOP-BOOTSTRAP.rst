iOS system volume through native MSDC
====================================

Current physical result, 2026-10-26: capture24 accepted native eMMC and
install4 wrote the bounded iOS system extent with a complete matching
readback. Capture27 mounted the small RAM bootstrap and exposed /dev/mtkios0,
but the project PID1 faulted before mounting that system volume. Its direct
C entry received an eight-byte-aligned Darwin argument stack and triggered
EXC_ARM_SP_ALIGN at the first stack-saving instruction. Image35 adds an
assembly entry that aligns SP before entering C. Capture30 verified that
correction on the phone: it mounted the physical iOS APFS volume, switched
roots, ran Apple launchd and spawned SpringBoard. The retained screen still
showed diagnostic syscall text, not the desktop. Image37 restricts those
syscall prints to the project bootstrap while retaining fatal exception
tracing for all processes; its physical result is pending. Apple's installed
executables are unchanged. See
../../physical/desktop-capture30-evidence.json and
physical-system-install-evidence.json. The entries below retain earlier
bring-up results; their pending states are superseded by this paragraph.

The read-only BSD adapter now optionally exposes a bounded system slice as
``/dev/mtkios0`` and ``/dev/rmtkios0``. Its start/count are64-bit sectors and
must fit entirely within the independently corroborated eMMC capacity.
Minor0 still represents the full card. All device-specific capacity/EOF
checks precede offset translation. APFS requests up to128KiB are supported.

The small project-built ``boot/desktop_bootstrap.c`` PID1 mounts that device
at/newroot, calls the port's existing one-shot root-switch facility, and
executes the existing helper init at/redwood/sbin/init. It neither rebuilds
nor patches Apple's userspace binaries. The tiny RAM filesystem remains
available at/redwood. The system APFS can therefore stay on eMMC rather than
occupy several GiB as a RAM disk. The optional physical handoff producer now
checks the captured LK profile; its real-device admission/card test is pending.
Image24/kernel42 enables the native MSDC probe. Capture21 rejects card
validation with error-7. Capture22/Image29/kernel45 records final R1=0x900,
which proves EXT_CSD data transfer completed before metadata rejection. The
earlier first-CMD13 interpretation was incorrect: the byte counter resets
for each command. BUS_WIDTH[183] is write-only and cannot validate card state;
the corrected driver checks inherited host mode and readable timing/capability
fields after the CRC-checked transfer. See ext-csd-validation-evidence.json.
The corrected build still requires physical acceptance. Image25
packages the same4MiB bootstrap used by the successful
emulator run and a bounded userdata slice, but is not installed. Its builder
and manifest checks passed. The separate ``physical/install_system_slice.py``
requires caller-supplied fresh device/partition guards, backs up the entire
target extent before any write, and verifies every written byte. It stops on
errors without retrying or resetting. No system slice has been written to the
phone yet. See ../../physical/desktop-build25-evidence.json.

Kernel33 mounted the unchanged system APFS and ran launchd in QEMU, but its
PIO transport latched a timeout under concurrent process startup. A host
regression reproduced a false timeout when the reader was descheduled while
the FIFO still contained data. The corrected loop bounds periods without
forward progress, rechecks hardware errors before final completion, and
retains terminal error behavior. It does not retry or reset the controller.
Timeout diagnostics record command, phase, transferred bytes and elapsed
stall from RAM, without additional MMIO after failure.

Kernel34 was rebuilt after genuine Mac interface regeneration; all34 generated
file hashes matched the preceding generation. The kernel linked successfully
with the existing donor export-check failures still outstanding. Its slice
probe passed nonzero-offset raw/block reads, a128KiB read, negative offsets,
partial EOF, EOF/beyond-EOF, read-only opening, and delayed data-CRC failure
that stays terminal after the model fault is cleared. Backing-file hashes
were unchanged. These are emulator results, not real eMMC acceptance.

The longer kernel34 run reached SpringBoard initialization but stopped making
storage progress after717,645,312bytes. Its CMD13 timeout recorded a stale
IRQ=0 after a21.645ms scheduling gap; the final model instead contained the
completed response IRQ=0x100/R1=0x900 with no backend error. The corrected core
now samples status once more at deadline expiry for both command and data
waits. Backwards-clock and bounded no-progress failures remain terminal.
Host regression tests reproduce a completion arriving between the status
and deadline reads. The long-run evidence records the failure, not a desktop
success. The kernel37 retry subsequently rendered the iOS home screen through
the modeled eMMC backend (snapshot016, about960seconds). It completed the
1800-second run with the home screen still visible,792,837,632bytes read,
zero backend errors and no terminal storage failure or kernel panic. This
duration includes boot. No gesture schedule was applied in that run, and
the donor's automatic unlock helper remains. See desktop-build37-evidence.json;
physical card acceptance remains a separate test.
