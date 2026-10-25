Passive inherited brightness snapshot
=====================================

Image12/kernel29 records the bootloader's DISP_PWM configuration without
changing clocks, pins, duty, enable, commit, PMIC or display registers. The
probe runs only after the existing live display validator admits the console.
A missing or rejected display leaves the PWM record untouched and preserves
the serial-only boot path. No native hardware handoff is produced.

The record is 256 bytes at physical address 0x40084300, immediately after the
phase and display records, below the reserved download-agent heap at 0x40090000.
Its magic is MTKPWM01, version1, with the same random build identity as the
phase record. It contains two separate snapshots with read-completion masks.
The state/complement pair distinguishes untouched, incomplete, unavailable
and complete observations. A stable complete record means both snapshots
agree; it does not prove native ownership or the external backlight wiring.

Read order
----------

* SPM power status at 0x10006180/184 and display control at 0x1000630c.
* TOP clock configuration at 0x10000080 and INFRA gate status at 0x100010ac.
* GPIO mode at 0x10005350; pin43 uses bits15:12, with mux1 named DISP_PWM.
* When parent encoding2/3 is selected, ULPOSC status at 0x10006458.
* Only with the domain on, both gates clear and any selected ULPOSC enabled:
  DISP_PWM0 enable/commit/CON0/CON1/debug at 0x1100e000 plus
  offsets 0x00/0x0c/0x18/0x1c/0x80.

The complete 32-bit register values are retained. No DATA/FIFO register,
read-to-clear interrupt register or pointer supplied by the peripheral is used.
The existing console remains active if the PWM probe declines the configuration.

Why measure rather than impose Android defaults
-----------------------------------------------

The existing stock-kernel/BSP audit in
``../hardware/display-touch/brightness-clock-audit.json`` establishes the PWM
clock selector, gate and register layout. Exact-stock LK disassembly adds a
different initialization path: get_cust_led_list at 0x4800017c returns the
table at 0x4808871c; its LCD entry at +0xc0 has mode5, callback0x48012249,
clock_source0 and divider0. The routine at 0x48012102 clears TOP mask03000000,
then its shifted zero source cannot select a different parent. This predicts
parent0/clk26m and divider0, but only the next physical snapshot can confirm it.
The Linux-derived native driver currently expects parent3/divider3. Do not
promote either static path to a live hardware configuration.

The GPIO function mapping comes from the exact stock kernel's mt6765 pin table
at VA0xffffff80097e2f28, pin43 entry and functions pointer0xffffff80097e5c88.
It identifies the SoC mux function, not board-level wiring or a backlight IC.

Validation and limits
---------------------

The host test executes the production C probe with an address allowlist and
injects each power/gate failure on both passes. It exercises all four clock
selectors, unavailable ULPOSC states, wire layout, partial records, changed
build identity and torn commits. The complete physical-payload suite passes
61 tests, including the pinned live-FDT and actual packaged-AVB fixtures.

The exact packaged Image12 boots to diagnostic PID1 in QEMU with serial and
the two-layer console. The QEMU display fixture lacks an enabled ULPOSC and
pin43 routing; the passive probe correctly records unavailable and leaves its
PWM untouched. This is not a positive hardware-brightness test. Host mocks
exercise complete reads; physical readback and a controlled visible duty test
remain necessary before claiming working brightness.

The earlier local Image11 candidate attempted passive reads even without an
admitted display and faulted in headless QEMU's unmodelled SPM region. It was
never installed. Image12 adds the display-admission condition and passes both
boot paths. Neither candidate changes the XNU kernel or Apple userspace.
