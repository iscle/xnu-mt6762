iOS system volume through native MSDC
====================================

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
The installed real-phone diagnostic does not enable MSDC or include iOS.

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
