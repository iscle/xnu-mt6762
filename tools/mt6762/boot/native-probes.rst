Native-driver laboratory probes
================================

These probes execute the native XNU I2C, AXS state tracking and input queue
against explicitly synthetic QEMU peripherals. They do not test the phone's
electrical buses, cache coherency, IOMMU routing, power sequence or drivers
on real hardware. The normal machine and loader defaults remain unchanged.

The QEMU patch series in ``../qemu`` supplies opt-in ``lab-i2c=on`` fixtures.
The loader's ``--native-lab-i2c`` supplies the corresponding versioned ADT
contract, labeled ``lab-fixture=1``. It grants ownership only for the modeled
I2C/pad/DMA and disable-only charger paths. It does not claim valid display,
PMIC wrapper, ADC or keypad state. Supplying ``--framebuffer`` deliberately
also tests that a native handoff lacking display validation cannot draw into
unverified bootVideo memory.

The static ``queue_probe.c`` program is PID1. It reads, never writes,
``/dev/redwood-touch`` and prints the actual kernel queue records. It has no
libc, dyld, Apple executable or shared-cache dependency. It remains blocked
when the queue is empty instead of exiting PID1. This removes backboardd and
injected user libraries from the native input-path test.

With the previously bootstrapped local compiler/linker and QEMU::

  tools/mt6762/boot/build_queue_probe.sh /new/probe-build
  python3 tools/mt6762/boot/prepare.py \
    --kernel BUILD/obj/DEVELOPMENT_ARM64_MT6762/mach.development.mt6762 \
    --out /new/native-queue \
    --clang "$MTK_LLVM_BIN/clang" --objcopy "$MTK_LLVM_BIN/llvm-objcopy" \
    --qemu /path/to/qemu-system-aarch64 --linux-dtb /path/to/boot.bin.dtb \
    --ramdisk /new/probe-build/queue_probe.macho --memory-mib 512 \
    --native-lab-i2c --framebuffer
  python3 tools/mt6762/boot/probe_native.py /new/native-queue/manifest.json \
    --seconds 4 --queue-mode cycle --label cycle
  python3 tools/mt6762/boot/probe_native.py /new/native-queue/manifest.json \
    --seconds 5 --queue-mode fault --label fault

``MTK_LLVM_BIN`` points to the same Linux LLVM directory used for XNU;
``MTK_WORKSPACE`` can override the default workspace. The queue build script
uses the isolated Theos linker, overridable with ``MTK_LD64``. No system
installations or phone connections are made.

Queue modes enable the synthetic contact sequence through QMP only after
the guest prints ``MT6762_QUEUE_READY``. ``cycle`` observes normal down/move/up
sequences, then disables the sequence and checks that no contact remains.
``fault`` waits for an actual guest MOVE record before injecting a DMA error;
it requires a matching UP after the driver's transport-error message, no
held contact, and no panic. QOM counters separately establish completed DMA
reads and charger-bus transactions; synthetic PSC register readback records
CE control and status. Every run is bounded and terminates its own QEMU.

The JSON and serial log are written alongside the manifest. When a synthetic
framebuffer is present, its captured bytes are compared with the initial
loader image. ``--expect-handoff-rejected`` accepts a deliberately malformed
handoff test only if neither bus is initialized, no transfer occurs, early
console and MiniFB reject video, and that framebuffer remains unchanged.
It does not alter the manifest or generate a malformed handoff itself.

For normal userspace tests, omit ``--native-lab-i2c`` and use ``run-ios.sh``.
That preserves the existing synthetic display/input path; a native test's
rejected display is intentional and is not a substitute for native panel
bring-up.

Inherited-display validation
----------------------------

Adding ``--native-lab-display`` to the preparation command above supplies
only the explicit synthetic model's complete display/brightness contract.
It also selects QEMU's display fixture with the exact allocated framebuffer
address. The framebuffer is part of the loader's reserved memory below
``topOfKernelData``; the range must fit below4GiB. This is not a captured
phone framebuffer or a physical scanout configuration.

A positive ``probe_native.py`` run on such a manifest additionally requires
native scanout and PWM validation. Read-only model counters record the
register accesses separately. A valid display may write framebuffer pixels;
the JSON still records whether it did. Passing this test does not establish
an Apple brightness request or duty change unless PWM writes/commits were
also observed.

Startup negative tests preserve all other native I/O and must reject display
without changing framebuffer pixels or writing PWM::

  python3 tools/mt6762/boot/probe_native.py /new/native-display/manifest.json \
    --seconds 3 --queue-mode cycle --display-fault power-off --label power-off
  python3 tools/mt6762/boot/probe_native.py /new/native-display/manifest.json \
    --seconds 3 --queue-mode fault --display-fault scanout-mismatch --label mismatch

The second command also proves release of a queued contact after a separate
DMA failure. These are independent failure conditions, explicitly reported
in JSON. ``test_lab_display.py`` in the QEMU patch series tests the model's
PWM dropped-write behavior without executing guest driver code.

Power, buttons and SSPM
-----------------------

``--native-lab-power`` selects explicit PWRAP/ADC/keypad fixtures; it requires
``--native-lab-i2c`` and supplies only their corresponding verified flags.
``--native-lab-sspm`` separately grants the synthetic PLATFORM/CPU mailbox
ownership contract. No CPU-DVFS commands are sent by these tests.

The static observer additionally reads native diagnostic sysctls using
Darwin's read-only sysctlbyname syscall. Actual kernel results are recorded
separately from model counters: valid conversion counts, battery/NTC ADC
millivolts, sample validity, CE-disable readback and SSPM liveness/fault.
These are synthetic voltages; an NTC ADC value is not calibrated temperature.

On a manifest prepared with both options::

  python3 tools/mt6762/boot/probe_native.py /new/native-power/manifest.json \
    --seconds 6 --queue-mode cycle --key-mode cycle --label keys
  python3 tools/mt6762/boot/probe_native.py /new/native-power/manifest.json \
    --seconds 5 --queue-mode cycle --key-mode power-fault --label power-fault
  python3 tools/mt6762/boot/probe_native.py /new/native-power/manifest.json \
    --seconds 5 --queue-mode cycle --key-mode keypad-fault --label keypad-fault

Key modes assert actual kernel queue button IDs1/2/3, matching releases and
no held button. Fault modes hold a key then invalidate PWRAP or keypad
readback; a matching release must follow. Touch queue records are checked
independently. ``--sspm-fault`` tests transport and ownership failures;
``stale-ack`` and ``stale-input`` must produce no mailbox data/control writes.

When ``--cpus`` exceeds1, every secondary CPU must report online before a
probe can pass. This demonstrates bounded native worker execution, not
long-running SMP iOS stability. A full iOS run on eight emulated cores has
exposed a ticket-spinlock timeout and is tracked separately from these
short native integration tests.

Native input into original Apple userspace
-----------------------------------------

``tools/mt6762/run-ios.sh --native-lab`` prepares a fresh owned experiment
with native I2C/power/display fixtures and a private root containing no
scripted ``rwtouch`` queue injection. ``--native-lab-prepare-only`` performs
all image preparation and Apple-file verification without launching QEMU.
The normal ``run-ios.sh`` mode retains the earlier synthetic GUI path.

The native mode uses one CPU by default. ``MTK_CPUS`` is explicit; eight-core
full-iOS stability is unresolved even though short native eight-core tests
pass. The current kernel is copied into the experiment before preparation.
``MTK_BACKLIGHT_PROBE`` may name the source-built, read-only registry helper;
its actual guest path is ``/redwood/bin/backlight_probe``.

``boot/native-input.json`` schedules a synthetic PMIC lock button, AXS taps
and a swipe. Each AXS frame must be consumed by two native DMA reads before
the next is published. ``capture.py --native-input-schedule FILE`` executes
these commands over the same QMP connection used for screenshots. It records
completed actions, model counters and input schedule hash. This proves only
the explicitly tested emulated peripheral path; inspect screenshots and
Apple logs separately before claiming that iOS accepted a gesture.

``--stop-on-panic`` preserves a final framebuffer plus bounded per-CPU HMP
register and frame-chain snapshots, then reports failure. The serial log
remains authoritative: an image, timeout or successful QEMU process exit is
not sufficient evidence of a completed iOS boot.

PMIC temperature freshness
--------------------------

``--native-lab-thermal`` additionally requires ``--native-lab-power`` and
selects only the synthetic PMIC thermal conversion fixture. The observer
reads die/buck temperatures, sample/error counters and observed/fresh masks.
No CPU thermal ownership is asserted; CPU temperature remains invalid.
Synthetic calibration and temperatures are not measurements of this phone.

``--thermal-fault timeout|stale|uncalibrated|bad-degc|mux|rail`` exercises
startup rejection. The mux fault is scoped to the die channel; independently
valid buck values remain allowed. ``--thermal-fault-after-fresh`` waits for
actual native sysctl fresh-mask7 before injecting the requested failure,
then requires invalidation. Use ``--queue-mode cycle --seconds 6`` so the
read-only observer continues sampling sysctls throughout the test.
