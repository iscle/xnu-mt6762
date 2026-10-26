Desktop bootstrap stack-alignment correction
============================================

Physical capture27 identifies the failure before the first bootstrap message:
PID1 takes EXC_BAD_ACCESS with code0x103 (EXC_ARM_SP_ALIGN), PC0x100003a50,
SP0x16fdffe18 and LR0. The exact build1 executable starts at0x100003a4c::

  0x100003a4c: sub sp, sp, #0x70
  0x100003a50: stp x29, x30, [sp, #0x60]

The second instruction is the reported fault. Subtracting0x70 preserves the
incoming stack's eight-byte misalignment; the original SP was0x16fdffe88.
``osfmk/arm64/sleh.c:handle_sp_align`` reports the stack pointer as the
exception subcode, exactly matching the capture.

``bsd/kern/kern_exec.c:exec_copyout_strings`` constructs a pointer-aligned
argc slot and returns its address. ``thread_setuserstack`` installs that
address unchanged. A static LC_UNIXTHREAD entry must establish the C ABI's
16-byte stack alignment before entering an ordinary C function. Both the
old desktop bootstrap and IIG probe entered C directly. The IIG probe's
successful launch does not establish alignment for different argument data.
Both executables otherwise use the same static ARM64 LC_UNIXTHREAD entry
form, four-GiB PAGEZERO and16-KiB segment boundaries.

The corrected bootstrap has a naked assembly entry::

  mov x0, sp
  and x9, x0, #0xfffffffffffffff0
  mov sp, x9
  b _desktop_main

This retains the original Darwin argc/argv area through its pointer in x0,
aligns the working SP downward, and enters a noreturn C function. The original
argument bytes stay untouched above the working stack. The current C bridge
supplies its own init arguments and does not parse the preserved initial
stack. Kernel exec setup and the rest of the bootstrap flow are unchanged.

Build2's entry is0x100003e94 and its C entry is0x100003a3c. Its SHA256 is
``f749024a376321a6d5ba31ff674103b4520420c67b6e61908ced37f505a1ba32``.
``desktop-entry-evidence.json`` retains the old/new executable hashes,
physical-log identity, source/build-command manifest identity and regression
results without including Apple binaries or private log contents.

Reproduce the targeted regression with the existing Capstone/Unicorn modules::

  python3 test_desktop_entry.py /path/to/desktop_bootstrap.macho \
    --output /path/to/entry-verification.json

The test validates LC_UNIXTHREAD's actual linked entry, executes the emitted
startup instructions for18 initial stack values, and reaches the first
console-open syscall. Cases include the exact original SP from capture27,
aligned inputs and every low-nibble alignment. It checks that C receives
the original pointer, all original argument bytes remain unchanged, and every
executed SP-relative memory access uses an aligned stack. Explicit invariant
checks supplement Unicorn; this is not a physical Cortex-A53 exception test
or an emulation of Darwin syscalls. No successful desktop boot is inferred
from these offline tests.
