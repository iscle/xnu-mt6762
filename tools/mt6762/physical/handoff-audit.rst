Physical LK to kernel handoff audit
===================================

This is bounded read-only evidence for preparing a temporary diagnostic image.
It is not a claim that physical XNU boot, a framebuffer console, peripheral
ownership or fastboot execution has succeeded. No phone commands, reboots,
register writes or storage mutations were performed by this audit. The user's
current unlocked-bootloader statement supersedes the older saved Android
``green``/locked report; that old report is not a current unlock check.

``audit_handoff.py --dump /path/to/dump --bsp /path/to/workspace --output report.json``
reproduces ``handoff-evidence.json`` using Capstone, exact artifact hashes,
14 selected LK code ranges and 62 allowlisted historical technical log records.
It excludes command lines, unique identifiers, partition UUIDs and OTP content.
The REA provider was unavailable earlier; the existing bounded format-aware
fallback was used without changing configuration. ``lk.bin`` and ``lk2.bin``
are byte-identical, SHA256
5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a.
The 512-byte MediaTek header precedes code linked at 0x48000000; the startup
literal at file0x274 corroborates this base. This differs from an obsolete
0x41e00000 comment in the reference kernel-decompression code.

Entry convention: exact code and historical boot
------------------------------------------------

The exact LK final path at 0x4801bc32..0x4801bc40 passes kernel entry in r0,
DTB in r1, zero in r2, and AArch64 selector1 in r3. Wrapper0x4801a03c calls
0x48026674, which builds SMC ID0x82000115 and places entry/DTB/zero/selector in
SMC arguments r1..r4. The shared trampoline executes SMC at 0x4802665e.

A retained normal-boot GZ line at expdb offset0x121737c states::

  boot linux-64 via EL2, pc=0x40080000, x0=0x47880000, x1=0x0, mode=0x3c5

The selected substring is retained with its exact offset in JSON. Mode0x3c5
is AArch64 EL1h with DAIF masked. Thus ``via EL2`` describes the hypervisor
transition, not an assertion that the guest starts in EL2. A second retained
boot agrees. Generic supplied ATF source instead chooses EL2h if EL2 exists;
that reference source is insufficient to override the exact GZ-mediated boot
record. The diagnostic must read CurrentEL on entry and support only explicitly
handled EL1/EL2 states; reject EL0/EL3, rather than assume QEMU's entry state.
Only x0/x1 are established by this record; preserve x0 before using scratch
registers and do not treat x2/x3 or an inherited stack as defined.

At 0x4801bb22 LK calls cache-disable0x48016a80 with argument3. The routine
clears AArch32 SCTLR.C and SCTLR.I and invokes cache maintenance. The call at
0x4801bb26 clears SCTLR.M through0x48017564/0x48016d44. Interrupt cleanup at
0x48002ca4 tails into0x48026b44, masks distributor sources and drains pending
CPU-interface acknowledgements. These establish LK's cleanup operations, not
readback of guest SCTLR_EL1 after GZ/ATF. The entry shim must check current
MMU/cache state, keep exceptions masked while relocating, clean written code
and invalidate instruction state before enabling translations. An EL2-to-EL1
path also needs deliberate HCR/timer-access/SPSR/stack/vector state; observing
EL2 alone is not permission to use guessed hypervisor settings.

The supplied DT identifies PSCI1.0 with SMC conduit and a13MHz timer. Initially
use one CPU, validate/read CNTFRQ and architectural feature registers, and avoid
CPU_ON, power-state and DVFS requests. The A53 supports4KiB translation granules;
16KiB XNU software VM pages remain distinct from its4KiB hardware page tables.
The Android boot-image storage page size is another independent value:2048.

RAM and reservations
--------------------

Stock boot header addresses and format are independently recorded in
``bootimg-stock-evidence.json``. Historical LK reservations were::

  decompression/kernel   0x40080000  size0x07800000
  DTB work area          0x47880000  size0x00080000
  ramdisk                0x51b00000  size0x04000000

LK returns these temporary allocations to its mblock map before entry. The
normal boot's total RAM is6GiB starting0x40000000, not the static DT's512MiB
placeholder. Its final14 persistent reservations are::

  0xbffff000  0x00001000  dramc-rk0
  0x1bffff000 0x00001000  dramc-rk1
  0x7f800000  0x00800000  gz
  0x7f600000  0x00041000  gz-log
  0x7f7c0000  0x00040000  log_store
  0x47d80000  0x00050000  atf-reserved
  0xbff70000  0x00080000  atf-ramdump-reserved
  0xbff30000  0x00040000  atf-log-reserved
  0x7f400000  0x00200000  tee-secmem
  0x7f700000  0x000c0000  SSPM-reserved
  0x47c80000  0x00010000  aee_debug_kinfo
  0x47c90000  0x000e0000  pstore
  0x47d70000  0x00010000  minirdump
  0x7ef90000  0x00470000  framebuffer

These are historical exclusions, not an exhaustive future allocation map.
LK fastboot also keeps its own image/heap and download buffer live until the
jump; the exact handler compares against LK0x48000000 and download0x48b00000.
Do not relocate over either while executing LK. Reference cmd_boot checks
kernel/ramdisk overlap and bounds, copies the ramdisk, stops USB and cancels
its watchdog service timer before entering the same boot_linux path.

The runtime DTB in x0 must be validated with bounded arithmetic and used to
reconcile all memory banks, reservation-map entries and enabled reserved-memory
reg ranges, including LK's dynamically added mblock nodes. Do not replace it
with the static dump DT and assume its reservations are complete. Size-only
reserved-memory nodes are allocation requests, not current physical addresses;
recognize that distinction and preserve known live firmware storage separately.
Runtime property reads through unprivileged ADB were denied in the retained
read-only evidence; node names alone do not supply current addresses.

A candidate minimal scheme is a small self-contained source Image at the stock
0x40080000 entry, bounded below the runtime DTB/low reservations, then selection
of one verified contiguous512MiB window at or above0x80000000 and below4GiB.
Only select it after checking the entire interval against the actual runtime
map, source image, DTB, stack, ramdisk and every reservation. Derive XNU physBase,
segment addresses, ADT/boot_args and memSize from that selected window; exclude
all other DRAM from XNU's allocator for this diagnostic. If no suitable window
exists, stop without writes to a candidate region. Historical free-looking
space is not an allocation certificate. A supplied dynamic DT is necessary but
not a universal proof of every peripheral's in-flight DMA ownership.

Framebuffer tag: exact layout, insufficient format proof
--------------------------------------------------------

The exact writer0x4800402c..0x480040bc agrees with selected atags.c:
``/chosen/atag,videolfb`` contains little-endian u64 fb_base at0, u32 islcmfound
at8, fps at12, vram at16, then a bounded NUL-terminated panel name at20. There
is no ATAG size/type header. Ordinary FDT address cells elsewhere remain big
endian; do not apply that encoding to this opaque payload. The writer pads
its returned length to words.

Historical tag values are base0x7ef90000, found1, fps6184, vram4653056
(0x470000), panel ``axs15260_dsi_6580_hd``. The tag contains no width, height,
stride, pixel format, active OVL layer, rotation or DMA translation state.
A correct base/reservation/name is therefore insufficient to expose BootVideo.
The reference main framebuffer uses a4-byte pixel pitch aligned to32 pixels,
and eBGRA8888 or eRGBA8888 selected by redoffset_32bit; it also enables a
separate boot-menu layer. The actual runtime display can differ from that
reference or remain composited with the fastboot UI.

For an optional visible diagnostic, read back power and clock-gate state before
accessing display engines, then require the existing narrow
``mt6762_display_core.h`` layout/OVL/RDMA/DSI conditions: reserved aligned buffer,
384x854, verified pitch, CFMT2/no swaps or rotation, exact memory source/address,
no competing layers, direct-link RDMA, and the known running video-mode DSI
configuration. Capture stable pre/post readback and reject any mismatch. This
performs no DSI/reset/clock/brightness write. The existing single-layer check
may legitimately reject LK's fastboot overlay; do not relax it by guessing that
another layer is harmless. Never substitute a synthetic QEMU framebuffer or
lab-verified flags. Without this proof leave all BootVideo fields zero. UART0
is0x11002000 with32-bit register stride4; the misleading DT node name contains
11020000, so use its reg property. Preserve inherited UART configuration.
Neither external UART accessibility nor successful physical display output
has been measured by this task.

Watchdogs and firmware ownership
--------------------------------

Exact final instructions0x4801bbca..0x4801bbd0 set timeout argument30, call
0x48042f50 (writes ``(30<<11)|8`` to0x10007004), then0x48042f6c (writes0x1971
to0x10007008). Historical LK mode configuration is0x7d, including enable, IRQ
and dual-mode bits. Thus30seconds is the programmed interval, not a proven
exact reset deadline: interrupt/dual-stage handling and GZ/ATF routing matter.
A diagnostic leaving the watchdog untouched must expect timeout behavior and
must not promise an indefinite boot session. Do not quietly disable or keep
feeding it as a substitute for a verified policy. PMIC/firmware watchdog state
is a separate concern and is not established by this AP interval.

Historical PWRAP lines report init_done1 and ``already init, do nothing``.
SSPM has a dedicated persistent reservation; LK marks its shared-memory DT node
okay. Platform uninit is interrupt cleanup, not a PWRAP/SSPM/charger shutdown or
an exclusive handoff. The initial diagnostic must omit native-io and all
peripheral-verified/owned properties, preserve firmware/PMIC/clock/rail state,
and avoid I2C, PWRAP, SSPM, MSDC, charger, GPIO/reset and panel-control operations.
Do not copy QEMU ``lab-fixture`` assertions into a physical ADT. The mandatory
peripheral work remains separate from this bounded RAM/entry diagnostic.
