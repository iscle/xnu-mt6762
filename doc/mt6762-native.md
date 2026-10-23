# Native MT6762 integration

This is the native driver implementation contract, not a physical-device
readiness certificate. The phone has not booted this kernel. The QEMU fixtures
exercise the actual XNU drivers but deliberately model only selected hardware.

## Initialization and ownership

There are two entry stages. `mt6762_platform_attach()` reads the Apple device
tree and publishes a validated versioned handoff; it performs no MMIO or DMA
allocation and can run before MiniFB starts. `mt6762_platform_init()` runs
after the BSD device filesystem is mounted and initializes the I2C resources.
Touch and power workers then use the registered platform transport. Qualcomm
board initializers remain excluded on MT6762.

Native operation requires `/chosen/mt6762-handoff`, with little-endian u32
properties `version=1` and `native-io=1`. A missing node preserves the existing
laboratory framebuffer boot. A present but malformed node does not permit
native display access. The early console suppresses boot-video writes for
every native node; the display consumer restores graphics only after its
scanout checks pass.

The handoff properties describe measurements and ownership that the loader
must actually establish. Setting a flag is not a substitute for doing so.
There is no physical loader producing this handoff yet. The laboratory loader
option explicitly labels its handoff `lab-fixture=1` and creates corresponding
QEMU devices. Each additional laboratory peripheral is explicitly opt-in;
the default I2C fixture does not assert display, ADC, PWRAP or keypad readiness.

## I2C, clocks, pins and DMA

Common u32 properties are `dma-direct=1`, `i2c-pads-verified=1`,
`i2c-parent-index`, and `i2c-parent-hz`. Each bus additionally requires
`i2c0-verified=1`/`i2c5-verified=1` and `i2c0-hz`/`i2c5-hz`.
Verified bus ownership includes inactive transactions, exclusive controller
and APDMA access, and no concurrent boot-firmware or SSPM owner.

The platform checks the TOPCKGEN parent selector against the handoff. For PLL
parents it reads enable, divider-reset, power/isolation and PCW/postdivider
state, then computes the rate through the exact parent divisors. It compares
the result with the declared rate. The 26 MHz crystal parent requires no PLL
programming. The driver enables the selected mux gate and the two shared AP
I2C/APDMA gates through SET/CLR registers, with readback. It does not change a
shared parent or PLL behind other consumers. Parent/gate changes during use
fault the bus instead of continuing with stale timing.

I2C0 requires GPIO82/83 mode1; I2C5 requires GPIO48/49 mode1. The driver checks
the live mux fields. Pad electrical settings, pullups and rail readiness must
come from the verified loader handoff; the driver does not infer them from
the mux alone. No touch reset or firmware erase/upload is performed.

The V2 timing calculator supports 10–400 kHz, divider1–8 and the recovered
sample/step constraint. It computes the 45/55 duty split above 100 kHz,
LTIMING, timeout, start condition and clock divider. Full-Hz ceiling arithmetic
avoids the stock driver's kHz truncation and overflowing sample0/step64
encoding. Native bus setup currently uses the DT divider5 and programs and
checks the actual timing registers. A target rate still needs electrical
verification on the board.

The controller GIC interrupt is disabled and both GICD RWP completion and
ISENABLER readback are checked before polling operation enables peripheral
events. Waits are bounded. Each bus has a separate wired, physically
contiguous VM page; its complete physical range must fit in the APDMA 33-bit
address space. The loader must establish direct APDMA physical addressing.
The kernel does not guess an IOMMU mapping.

The same transaction core is compiled by XNU and host tests. Up to eight
bytes uses FIFO; longer transfers use APDMA. The private page is cleaned and
invalidated before device ownership, and receive data is invalidated only
after both controller and DMA are idle. No CPU data is published on error.
An error faults the bus and keeps the DMA allocation pinned; there is no
automatic reset/reuse that could race outstanding DMA. Callers serialize
complete higher-level read/modify/write operations in addition to the
transport's per-transaction mutex.

## Touch and display

Touch requires `touch-verified=1`, bus0, address0x3b and maxima384/854. It reads
and requires firmware version0007, then polls the exact 32-byte frame through
APDMA. The five-contact tracker posts normalized events to the existing
Redwood device queue. Transport failure, malformed-frame limits and stale
contacts release held fingers. Synthetic contacts are opt-in QEMU fixtures.

Display validation is intentionally narrow: the recovered 384×854 BGRA OVL0
pipeline, one active layer, reserved framebuffer bounds, matching physical
addresses/strides, and running power/gates/DSI state. It checks the virtual
console's backing pages after mapping. The loader must independently establish
the framebuffer reservation and display DMA translation; readback of an OVL
address alone does not prove either. See the display package for all handoff
fields and exact register checks.

The native PWM implementation updates duty, enable and commit in order,
preserves unrelated bits and validates readback. Its privileged engineering
property is `MT6762Brightness` with range0–1023. An `AppleARMBacklight` service
also implements the exact precompiled CoreBrightness property interface:
integer `brightness`, 16.16-second `FadePeriod`, and `backlight-level`. It
admits the stock backboardd display entitlement or administrator access,
performs timed fades from measured duty, and verifies PWM writes. Loss of
clock/power or failed readback disables control. Host tests and synthetic
PWM tests pass; actual CoreBrightness-to-driver acceptance is still being
tested. Native panel cold-start, blank/unblank and suspend remain incomplete.

## CPU topology and firmware coordination

The loader supports one through eight CPUs, with MPIDRs 0–3 and 0x100–0x103.
XNU retains physical cluster IDs for reset, GIC and DVFS. This Clutch build
uses one SMP scheduling set: its non-Edge shared-bucket implementation assumes
the pset0 lock. Creating a second set caused a reproducible boot lock panic;
the single-set configuration brought all eight emulated A53 cores online.
It does not yet prefer the faster clock domain or implement a governor.

The native CPU observer verifies stable CPU/CCI PLL and divider snapshots,
PWRAP voltage selectors, and the recovered C62 SSPM PVT/PPM table before
publishing values. Programmed voltage and nominal frequency are register
readbacks, not physical measurements. The confirmed stock C62 ceilings are
2.001 GHz for CPUs0–3 and 1.5 GHz for CPUs4–7. Shared rails and CCI must remain
coordinated; the driver does not directly write PLLs or voltage selectors.

`sspm-mailbox-owned=1` additionally transfers exclusive AP PLATFORM/CPU
mailbox slots and acknowledgement ownership. The bounded SSPM transport
requires the former mailbox IRQ to be disabled and inactive, rejects pending
traffic, and probes PLATFORM with the exact stock `0xDEAD` command. Physical
operation also requires `sspm-firmware-preserved=1`, asserting the active
firmware/shared-memory reservations and EMI permissions survive the handoff.
No physical loader establishes that assertion yet. This is
an active firmware transaction. An acknowledgement must be consumed with
the input bit cleared; timeout or ownership loss faults the transport.
No stale acknowledgement is cleared during attachment. A successful recent
PLATFORM response establishes liveness only: it does not establish CPU-DVFS,
EEM or thermal-policy readiness, and frequency control remains disabled.

## Power and charging

The power worker uses independent `pwrap-verified`, `adc-verified`,
`keypad-verified` and `charger-verified` gates. PWRAP must already be initialized
and exclusively owned. Read/write transactions have bounded FSM waits and
fault on lost initialization or timeout. The PMIC identity is checked.
Native keys are debounced; volume up/down use the actual keypad matrix
indices, and power uses the PMIC. Invalid readings release held keys.

The thermal observer reads live calibration efuses and serializes PMIC
die/VCORE/VPROC ADC requests with the battery ADC. The additional
`pmic-thermal-adc-owned=1` contract covers the initialized channels and CH4
mux. It requires a READY low-to-high conversion transition, rejects generic
calibration fallbacks, and expires observations after two seconds. Independent
execution of the original stock calibration routine validates the integer
formula, including nonzero slopes and both signs. These PMIC temperatures
are not battery-cell temperatures. CPU sensor readbacks are calibrated
diagnostics only: their conversion freshness is not established and they
cannot authorize DVFS. See the [thermal evidence and limits](../tools/mt6762/hardware/cpu-power/THERMAL.rst).

Battery samples carry explicit field-validity bits. IOKit removes values
that become unavailable. Uncalibrated nominal thermistor conversion is
diagnostic only; capacity, current and protected charging temperature are
not fabricated. ADC requests and readings have their own counters and bounds.

Charging control currently supports verified disable only. A real native
handoff must transfer charger control explicitly and leave the charger in a
verified safe state before jumping to XNU. An unresponsive bus cannot prove
the charger disabled; a hardware DISABLE fallback has not been established.
Full charging enable still needs board-specific current-sense resistance,
cell limits, USB input budget and calibrated thermal protection. The primary
PSC5425E datasheet resolves the non-linear CV table and register semantics;
those register definitions do not by themselves establish board calibration.

## Validation and remaining work

`tools/mt6762/test-host.sh` exercises shared protocol and loader code. Build
reports now hash tracked and new kernel inputs before and after compilation,
including shared protocol headers. A source change during the build rejects
the artifact. Export/symbolset failures inherited from the reference remain
reported separately and are not described as a fully passing build.
`tools/mt6762/boot/prepare.py --native-lab-i2c` opts into the controller fixture;
`--native-lab-touch-events` separately enables synthetic AXS contacts. These
options must not be used to construct a physical handoff. `--native-lab-display`
adds a synthetic OVL0/DSI/PWM contract and model; negative power/scanout
readback tests leave framebuffer memory untouched.

On kernel `a64921f52d56f7455ddefe001e11d438dc786da51c859f80bb7b59d30528191c`,
the eight-CPU native queue run observed all secondary cores online, 18 downs,
270 moves, 18 matching releases, 1161 touch DMA reads and 59 charger
transactions without a panic. A separate DMA-fault run released its held
contact after the transport error. These are synthetic-model results;
they do not establish physical cache coherency or electrical correctness.

The subsequent long native eight-CPU iOS run on kernel `77ef4533...` reached
the Apple-logo display but hit a ticket-spinlock timeout. Its cause is not
resolved; short SMP/input tests do not establish a stable eight-core GUI.
The independent single-core native run reached the original iOS home screen
at 430 seconds without a panic. Its private root issued no `rwtouch` commands;
Apple backboardd logged keys and touches delivered through the PMIC/AXS native
workers. The model counted 44,150 touch DMA reads. The donor still contains
an automatic-unlock helper, so the earlier native swipe is not credited with
causing the home-screen transition. PWM writes remained zero; an explicit
original-framework brightness-change test is still in progress.
Compact pass/failure evidence is recorded in
[`native-integration.json`](../tools/mt6762/evidence/native-integration.json).

The ordinary no-handoff GUI boot remains a separate regression test of the
precompiled Apple userspace. Native peripheral test results must be reported
separately from that GUI result. CPU/CCI SSPM DVFS, full PMIC/gauge/charging
policy, physical display handoff/cold-start, storage, USB, suspend and the
real boot entry remain incomplete. The active goal is not complete.
