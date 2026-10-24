Exact-image emulator diagnostic
==============================

``probe_payload.py`` reads the delivered Android boot-v2 image, verifies its
Android image ID and DT table, decompresses its kernel gzip, and loads only that
Image and the image's FDT. It does not load external XNU segments, Apple device
tree, boot arguments, or userspace. The private loader must materialize all of
those from its own embedded payload.

The synthetic LK handoff starts the CPU at0x40080000 with x0=0x47880000 and
x1..x3=0. Register numbers and sizes are read from QEMU's GDB target XML and every
write is read back. The reset state is EL1h with MMU/cache disabled and13MHz
counter frequency; these values and the final architectural registers are
recorded. This tests the EL1 path only. It does not emulate LK, TrustZone,
watchdog expiration, the physical PMIC, or an actual fastboot transfer.

The positive FDT changes only the existing memory/reg size to4GiB, matching
QEMU RAM. All six original dynamic reservation constraints remain. The loader
selects0xd0000000 for its512MiB XNU window. ``--static-memory`` instead retains
the original512MiB FDT and requires no-window refusal before any XNU entry.

``--display-fixture`` additionally adds a labeled synthetic little-endian LK
videolfb tag and an exact header reservation at0x7ef90000 of size0x470000. It
enables the existing synthetic display/I2C register fixtures solely to test
readback admission. It does not add native-driver ownership properties to the
embedded Apple tree. The probe records display counters and saves the actual
guest framebuffer. A successful test requires zero display-register writes.

Example (use a new output directory for each run)::

  python3 tools/mt6762/physical/probe_payload.py \
    --image /path/to/mt6762-xnu-diagnostic-boot.img \
    --qemu /path/to/qemu-system-aarch64 \
    --output /new/path/probe-headless

Repeat with ``--static-memory`` and ``--display-fixture`` into separate output
directories. The display path needs Pillow to encode the captured BGRA pixels;
the headless path uses only Python's standard library.

Observed results
----------------

Physical build1 stopped at an alignment abort in the FDT parser: compiler
coalescing emitted ``stur x11,[x9,#4]`` at0x400830b4, FAR0x40fa85fc,
ESR0x96000061. With the MMU off, unaligned Device accesses are invalid. The
producer was corrected to use ``-mstrict-align``. Its assembly fatal handler
also required ``-ffixed-x28`` so C could not reuse the recursion-guard register.
The failed image and reports were retained separately.

Build2 image SHA256
``58b7dcada7dac919ba1d8727718505233c13378108ecdfdd2a9f0318202ffe41``
passed all three scenarios: headless startup, original-FDT refusal, and
inherited-display startup. Both positive runs reached embedded PID1, which read
IIG result1/cases205 twice. XNU printed VM page16384/hardware page4096. The
display capture visibly contains XNU startup text; its last visible text is
serial-kdp initialization, while the UART log proceeds to the PID1 result.
The probe therefore does not claim that the PID1 result is displayed onscreen.

The first display fixture was rejected because its synthetic videolfb tag was
not padded to a four-byte size. That failed fixture remains preserved; padding
the test tag fixed the test without changing the delivered image.

These results establish execution of the packaged loader and its embedded
payload under the stated synthetic handoff. They do not establish physical
boot success, actual display ownership, or complete iOS peripheral readiness.

Visible-console build3
---------------------

Image SHA256
``5af8c1dfb459e0f3f4eec4f38c05c8aa4031874348af6a5784d07766cb78f381``
changes the boot argument to ``serial=0`` so XNU retains the admitted video
console. The captured screen directly shows ``MT6762_IIG_PROBE_READY``, both
passes with result1/cases205/error0/size4, and ``MT6762_IIG_PROBE_DONE``. Text
wraps at48columns; the full screenshot was visually inspected. Display
register-write counters remain zero. The unchanged static-memory refusal
test also passes.

For this mode use ``--display-fixture --visible-console``. The automated probe
checks loader/XNU entry, page sizes, display admission, framebuffer contents,
and write counters, then records ``passed:null`` pending separate visual review.
It preserves UART observations independently and never substitutes them for
visible text. The reviewed build3 result is recorded in
``payload-build3-probe-evidence.json`` and the run's ``visual-review.json``.

The build3 headless test is incomplete: kprintf reaches BSD startup but PID1
console text is absent from UART. The no-video fallback does not suffice to
restore that output with this boot argument. Its report remains failed;
build2's earlier headless205-case success is not relabeled as a build3 result.

Conditional-console build4
--------------------------

Final image SHA256
``049ed1cb4c825c7606e21aef68fed91a98c6b4638cdeddabc25726c967ad8b05``
keeps ``serial=3`` by default and changes the known command-line byte to0 only
after framebuffer readback admission. All three exact-image scenarios pass:
headless PID1 prints two result1/cases205 passes and DONE; the original512MiB
FDT refuses before XNU; the admitted display visibly shows READY, both
successful205-case passes, and DONE. Display-register writes remain zero.
``payload-build4-probe-evidence.json`` records input hashes, architectural
state, automated checks, and the separate direct visual review. Physical
execution remains outside this emulator evidence.
