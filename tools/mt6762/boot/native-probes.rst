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

For an isolated SMP reproduction, ``capture.py --host-scheduling`` also maps
QEMU vCPU IDs to Linux host thread IDs and records cumulative ``schedstat``
runtime, runnable-queue wait and timeslice counts at the existing polling
interval. The companion ``.host-scheduling.json`` records unavailable counters
and the host accounting setting explicitly. Collection is bounded to2048
samples and changes no host scheduler settings. These counters can establish
host contention; they do not establish that contention caused a guest timeout,
and zero counters do not prove its absence when accounting is disabled. Keep
the default guest lock timeout and preserve failing runs and register captures.

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

Gauge current snapshots
----------------------

``--native-lab-gauge`` requires native power fixtures and asserts their
explicit synthetic live calibration. The observer reads current in uA,
validity, raw current, completed snapshots, errors and transport fault. The
first snapshot is only a liveness baseline. The synthetic raw100 value maps
to31400uA after counter progression; it is not a measurement of this phone.

``--gauge-fault timeout|latch-stuck|stale|clock|calibration|counter-stuck``
exercises startup rejection. ``--gauge-fault-after-valid`` waits for an actual
native current-valid1 sample before injecting the fault and requires
current INT_MIN/valid0 afterwards. Use ``--queue-mode cycle --seconds 6``.
IOKit battery publication is checked separately by the read-only
``battery_probe`` helper; unknown capacity/temperature/cycle fields must
remain absent rather than fabricated.

BIF generation and ownership diagnostics
---------------------------------------

``--native-lab-bif`` requires ``--native-lab-power`` and supplies an explicitly
synthetic, already-clear TDET/configuration contract. No TDET write is
permitted. The queue observer records raw BIF/NTC, pair freshness, samples,
errors and faults; these raw values are not calibrated battery temperature.

The independent model test is ``tests/mt6762/test_lab_bif.py`` in the QEMU
fork. Native ``probe_native.py --bif-fault`` covers admission/configuration,
stale generation, timeout, rail and ownership drift; ``--bif-fault-after-fresh``
requires an observed valid raw pair before fault injection. The malformed
handoff check ``--expect-bif-rejected`` additionally requires zero BIF
requests. Model TDET-write attempts must always be zero for native probes.

Default80us conversions may finish before the TCG guest can observe
READY-low. Those results are invalid, not silently reused. The explicit
loader option ``--native-lab-adc-delay-us 2000`` provides a distinct slower
synthetic fixture for protocol acceptance tests; manifests and result JSON
record the override. Native freshness checks are identical. Default80us
rejections and slow-fixture positive results must be reported separately.

``--bif-clear-after-rejection`` is a separate startup-fault recovery test.
It waits for native invalid raw values, freshness0 and an error before
clearing the synthetic model fault. For stale-generation faults it requires
observed last-error-5/generation-rejection followed by a new valid raw pair.
For ownership/configuration/timeout/rail failures it instead requires the
native fault to remain latched after the model is externally repaired. The
captured pre-clear native and model snapshots distinguish recovery evidence
from merely starting with a healthy device.

Publication deadlines without new reports
----------------------------------------

The paired options ``--native-lab-battery-gap-start-ms`` and
``--native-lab-battery-gap-ms`` select a default-off, explicitly synthetic
publication gap. The native hook requires ``lab-fixture=1`` and bounded
start1000..300000ms/duration2000..10000ms. Time starts at the first native
report delivery opportunity, not guaranteed successful IOKit publication.
Only report delivery stops; acquisition and button polling continue. No
peripheral writes are added by this hook.

For the static observer, a5000ms start/5000ms gap and15second run exercise
BSD getter expiry and recovery. ``probe_native.py`` requires valid voltage
before the gap, repeated coherent expired BSD values during the gap,
continued ADC requests, and recovered fresh voltage afterward. Unknown SOC
and battery temperature remain unavailable. Separate getters can straddle
a boundary, so partially transitioned observations are not treated as a
coherent sample.

For original Apple IOKit, prepare a new run with
``MTK_NATIVE_BATTERY_GAP_START_MS=60000``, ``MTK_NATIVE_BATTERY_GAP_MS=8000``,
``MTK_NATIVE_GAUGE=1`` and the source-built read-only
``MTK_BATTERY_PROBE``. Set ``MTK_BATTERY_PROBE_REPEATS=100`` and
``MTK_BATTERY_PROBE_INTERVAL_MS=1000``; capture130seconds. The helper copies
one property dictionary for each service and reports native BSD validity
and acquisition counters separately. Validate its serial log with::

  python3 tools/mt6762/boot/check_battery_expiry.py SERIAL_LOG \
    --require-current --output NEW_RESULT_JSON

The validator selects only ``MT6762Battery`` and requires original IOKit
valid measurements, repeated expired observations with validity0 and all
measured properties absent, then fresh recovery. ADC acquisition must
continue during expiry; unknown capacity, SOC-related fields, temperature,
cycle count and time remaining must stay absent. Any publication-boundary
snapshots are retained explicitly. This is emulation evidence, not physical
battery validation or a new source of battery capacity/temperature data.

Read-only MSDC with a real file backend
--------------------------------------

``make_msdc_fixture.py NEW_RAW_FILE`` creates a small deterministic synthetic
raw file plus hashes for selected sectors. It refuses existing destinations
and makes the resulting file read-only. Neither generated binary belongs in
the source patch series. The QEMU MSDC fixture reads this actual file through
a read-only raw BlockBackend; it does not supply canned sector payloads.

``prepare.py --native-lab-msdc-image FILE`` enables only the explicit MSDC
fixture and the common synthetic handoff. Other peripheral fixtures remain
independently selected. The loader records actual file size/capacity/SHA256
and the agreed synthetic inherited configuration, including200MHz card-clock
metadata. No physical rail, pad, PLL or tuning state is asserted. These
properties must not be copied into a phone handoff as hardware evidence.

Build the standalone static guest observer with ``build_msdc_probe.sh`` and
use its Mach-O as mockfs RAMDisk0. ``probe_msdc.py MANIFEST`` checks the native
raw and block device paths, geometry/read-only ioctls, O_WRONLY rejection
without issuing any storage write, selected sector hashes, unaligned reads
crossing a sector boundary, partial near-EOF reads and exact/beyond-EOF
behavior. Full host-image hashes before and after the bounded run must match.
The observer writes only serial diagnostics and leaves PID1 alive afterward.

Startup ``--fault`` cases reject inherited admission, except ``backend-error``:
synthetic CMD8 metadata can be admitted before the first real-file read attempt
fails. That case must latch the transport without copying user payload. With
``--fault-after-first-read``, the host first observes actual valid guest data,
then injects a synthetic controller failure. Subsequent failed reads must
not copy data into the sentinel buffer. ``--clear-after-error`` separately
checks that repairing the model does not silently reset a latched native
transport fault. Model/QTest results and native guest results are independent;
source availability is not a passing native test claim. No real device is
opened by these tests and no filesystem-mount success is inferred from raw
block reads.
