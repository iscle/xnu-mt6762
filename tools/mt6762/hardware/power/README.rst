MT6762 board power and button protocol research
=============================================

This is an independently testable transport/protocol backend, not a completed
XNU battery/charging driver. Authorized passive stock Android ADB observations
are saved separately in hardware/live-power. No XNU hardware charging, battery
state of charge, or physical button operation is claimed.

Evidence and provenance
-----------------------

These are ordinary local artifact/source observations, not invented REA tool
results. The stock Image SHA256 is
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
The recovered stock ELF SHA256 is
643474799f7c300f2d3c7f5130f697ee359929f13db0750f4dd7b9d648af14fc.
NDK LLVM objdump generated the bounded function disassemblies in evidence/.
The kallsyms virtual base maps Image offset zero to 0xffffff8008080000.
extract_evidence.py saves only narrowly selected power probe lines with original
byte offsets and the expdb hash. It does not export the full device log.

Observed actual hardware
------------------------

The stock boot log reads PSC5425E register 3 as 0xf0, reports exist=1 and
successfully probes it. ETA6947 reads the same value, reports exist=0 and its
5-0063 probe fails. Driver registration alone does not identify a device.
The PMIC reports MT6357 CHIP Code 0x5730. Runtime input paths show mtk-kpd at
0x10010000 and mtk-pmic-keys under pwrap 0x1000d000.

The pure boot DT places PSC5425E on I2C5, 7-bit address 0x6a. I2C5 controller
MMIO is 0x11016000/0x1000; DMA is 0x11000580/0x80; IRQ SPI130; SCL/SDA GPIO48/49.
The common DT controller data selects ver=2, dma_support=2, idvfs=1,
set_dt_div=1, check_max_freq=1, set_ltiming=1, ext_time_config=0x1801
(a big-endian u16 property), and cnt_constraint=1. BSP i2c-mtk.c
mt_i2c_parse_comp_data loads these, rather than choosing from the generic
compatible string. Clock gates, pin multiplexing, actual transfer timing and IRQ servicing still
require an XNU I2C controller driver. The backend deliberately accepts an
injected I2C transaction implementation. It is not a fake I2C hardware model.

Exact stock protocol and caveats
-------------------------------

psc5425e_read_byte at 0xffffff8008a76548 constructs two Linux i2c_msg records:
write one register-address byte, repeated START, read one byte from the same
client address. Success requires two completed messages. psc5425e_write_byte at
0xffffff8008a7662c writes one two-byte register/value message. No fixed-address
substitution occurs in these functions.

The real charger callbacks, rather than similarly named generic setter wrappers,
recover these register fields:

* enable_charging 0xffffff8008a77720: Reg1 bit2 is active-low charge enable.
  The logged enable trace is fc -> f8; disable is f8 -> fc.
* set_current 0xffffff8008a777a4: Reg4 mask7 shift4. Argument thresholds for
  successive codes 1..7 are 656001,786001,1048001,1180001,1442001,1574001,1836001.
  These are observed software comparisons, not verified electrical currents.
* set_cv_voltage 0xffffff8008a77894: Reg2 mask0x3f shift2. Arguments <=4100000
  select code0; <=4200000 code2; <=4350000 code44; larger values code45.
  The unusual mapping is preserved as evidence, not used to choose voltages.
* set_input_current 0xffffff8008a77938: Reg1 mask3 shift6; arguments <=50000
  select code1, others code3. The apparent unit mismatch needs verification.
* get_charging_status 0xffffff8008a77be0 reads Reg0[5:4] and returns equality
  with code2 as its completion boolean. Other status/fault meanings remain raw.
* get_current and get_input_current are stubs returning success without storing
  an output value. reset_watch_dog_timer reads and rewrites Reg0[5:4]; its name
  alone does not establish the actual watchdog-kick semantics.

The backend exposes ID-checked snapshots and charge-disable only. It requires
complete transfer counts, preserves outputs on failure, preserves unrelated
Reg1 bits, checks disable readback, and never manufactures current or SOC.
The caller must serialize complete operations. No automatic enable, guessed
initialization register set, voltage/current limit, OTG or watchdog write is
provided. Stock config_interface ignores a failed read before writing; this
unsafe behavior is intentionally not reproduced.

PMIC wrapper and buttons
------------------------

BSP kernel-4.14/drivers/soc/mediatek/mtk-pmic-wrap.c mt6765_regs and pwrap_read16
specify WACS2 CMD/RDATA/VLDCLR offsets 0xc20/0xc24/0xc28 from 0x1000d000.
The exact stock mt6765_regs table at 0xffffff80097ef918 contains those values.
A 16-bit read command is (even_pmic_address >> 1) << 16. RDATA bits18:16 are
FSM state (idle0, wait-valid-clear6), low16 is data; init-done bit21 must be set.
The backend requires initialized hardware, exclusive WACS2 ownership, ordered
MMIO callbacks and bounded polls. It does not initialize SPI clocks, cipher,
PMIC rails or reset controls. A timed-out wrapper needs explicit recovery;
this backend returns an error rather than inventing data or issuing resets.

BSP include/linux/mfd/mt6357/registers.h defines TOPSTATUS0x24: PWRKEY_DEB bit1,
CHRDET_DEB bit2, HOMEKEY_DEB bit3. Key debounce levels are active low. The stock
4.19 driver uses dedicated press/release IRQs for MT6357: press handler reports
1 directly, release handler reports0. The BSP 4.14 key driver lacks MT6357
matching and must not be copied wholesale. Stock mt6357_regs key table at
0xffffff80090de04c has two identical legacy debounce descriptors but independent
release enabled; those legacy masks are not suitable for direct polling.
PMIC IRQ-domain indices are power48, home49, power-release50, home-release51
per include/dt-bindings/mfd/mt6357-irq.h.

The boot DT maps PMIC power to Linux116 and PMIC home to Linux115 (volume-up).
The keypad overlay maps matrix index0 to Linux114 (volume-down) and index1 to
115. Physical press/release observation on stock Android confirms both volume
buttons report through mtk-kpd/event0, and power through mtk-pmic-keys/event1.
The PMIC's advertised volume-up capability did not produce an event in that
test. Native register-to-button operation is still untested. KP_MEM1..5 are
16-bit reads at offsets
4,8,12,16,20 from 0x10010000; matrix bits are active-low. The helper decodes
matrix indices only, not an assumed physical-button mapping.

Battery and thermal policy evidence
-----------------------------------

The DT has an MT6357 gauge with AUXADC battery temperature channel3 and battery
voltage channel1, plus BIF/PTIM channels. Raw properties include R_FG_VALUE=10,
CAR_TUNE_VALUE=100, pullup resistance16900 and pullup voltage1800, six battery
profile tables and nvmem SOC. These are data to reconcile with the exact 4.19
parser and board calibration; they are not yet validated units/defaults.
BSP mt6357/v1/mt6357_gauge.c requires latch handshakes and sense-resistor and
car-tune scaling; the Android implementation also uses a battery daemon.
No percentage estimate or native ADC measurement is implemented here. The
thermistor helper converts supplied ADC/pullup measurements using the recovered
nominal NTC table; this is not a calibrated temperature provider.

The charger DT selects Basic algorithm, configured battery CV4350000,
USB current500000, and overlay AC/input/charging-host current1800000. JEITA
configured thresholds are T4=50C with47C recovery, T3=45C with39C recovery,
T2=10C with16C recovery, T1=0C with6C recovery, T0=0C. Configured JEITA CVs
are 4240000,4240000,4340000,4240000,4040000,4040000 by descending zone.
The simpler thermal policy has min0/recovery6 and max50/recovery47.
There is no enable_sw_jeita property in the examined DT/overlay. BSP
mtk_charger.c reads that boolean separately, so the presence of threshold
properties does not establish active JEITA policy. Exact runtime policy,
watchdog, USB source classification, NTC open/short handling, gauge calibration,
and safe cell limits must be verified before enabling charging under XNU.

Validation and remaining integration
------------------------------------

Run ./test.sh. The host test checks the actual fc/f8 disable trace, complete
I2C transaction structure, read failures/short transfers, no writes after failed
reads or wrong ID, status decode, WACS2 command/wait/ack, timeout/uninitialized
wrapper rejection and active-low key decode. Host tests pass with -Werror.
ASan/UBSan were attempted but host runtime libraries are missing; sanitizer
coverage is not claimed. These fixtures test recovered protocol, not hardware.

Remaining work: real XNU I2C/pwrap/PMIC interrupt providers, GPIO/clock setup,
IOHID button integration, calibrated gauge/ADC driver, battery power-source
publication, source/current/voltage limits and thermal/watchdog state machine,
suspend/wakeup behavior, and instrumented physical-device validation. No
charging acceptance criterion has been met by this isolated backend.

Live validation and recovered thermistor path
--------------------------------------------

Passive stock Android confirms PSC5425E device5-006a and PMIC/keypad input
capabilities. The stock battery supply reports Charging but its25C temperature
is hardcoded: temperature_get at0xffffff8008a80704 loads immediate250 and25,
stores250 at state+0x33c,25 at state+0x494 and+0x150 and through output pointer.
No ADC is read. gauge_initialized_get at0xffffff8008a88508 is a success-only
stub, explaining why exported gauge_initialized0 is not trustworthy readiness.
Bounded exact disassemblies are in evidence/.

The separate battery_temperature_adc_get at0xffffff8008a875fc calls
iio_read_channel_processed using the gauge BAT_TEMP channel. Passive readings
were614mV for this channel and1797mV BIF. The DT assigns BAT_TEMP channel3,
ratio1/1. BSP mt635x-auxadc.c requests bit3 at PMIC0x110e, waits for bit15
ready at0x108e, extracts12bits and converts raw*1800/4096 to mV. BIF channel14
uses hardware channel11/request bit11/output0x109e,12bits. Request/poll
semantics, per-channel convert hooks, clock/rail setup and serialized access
need exact driver integration before native sampling. The backend has no
ADC request writes and makes no claim of initializing ADC hardware.

Fg_Temperature_Table at stock VA0xffffff800987b7d8 contains21 signed-temperature/
resistance pairs from-40C/195652ohm through25C/10000ohm to60C/3014ohm; its
extraction is recorded in evidence/fg-temperature-table.json.
BattThermistorConverTemp at0xffffff8008a7bac0 linearly interpolates that shape
and returns deci-C. BattVoltToTemp at0xffffff8008a7bbfc computes the divider
resistance using configured pullup, measured BIF plus compensation if available
(or configured pullup voltage on explicit unsupported return).
force_get_tbat_internal at0xffffff8008a7be28 reads ADC and gauge current and
applies sense-path resistance compensation before conversion. Its call path
is distinct from the constant sysfs temperature_get. Full correction settings
and the selected runtime table require verification.

thermistor.c provides only the nominal recovered table/divider interpolation,
with explicit pullup voltage/resistance inputs and rejection of invalid rail
values/out-of-table resistance. It returns errors rather than clamping sensor
faults to a plausible temperature. The passive614/1797mV and configured16900ohm
produce an uncorrected28.6C estimate. This is not validated thermal safety.
Physical NTC/pullup calibration, current compensation and independent measured
temperature are prerequisites for a native charging-enable policy.

Native status and presence corroboration
---------------------------------------

``psc5425e_chg_get_property`` at 0xffffff8008a77570 handles property 0
(POWER_SUPPLY_PROP_STATUS). At 0xffffff8008a77660 it reads register 0 with
mask 3 and shift 4. The four-byte jump table at 0xffffff80090f50c8 is
00 04 06 00, indexing four-byte instructions from 0xffffff8008a776ac.
The targets set Linux status 3, 1, 4, 3 respectively: not charging, charging,
full, not charging. This is the exact stock interpretation, independent of
the enable bit. See ``evidence/psc-status-jump-table.json`` and the existing
PSC disassembly. The native driver checks a successful transaction before
using this table; it does not reproduce the stock ignored-read-error issue.

``battery_exist_get`` at 0xffffff8008a87464 explicitly reads 0x0e08 and
returns !bit1. See ``evidence/battery-presence-disassembly.txt``. BSP
``include/linux/mfd/mt6357/registers.h`` calls 0x0e08 BATON_ANA_CON0,
bit 0 RG_BATON_EN and bit 1 RGS_BATON_UNDET. Native observation additionally
requires enable bit 0, since a disabled detector is not evidence of presence.
Stock's absent-battery path pulses AUXADC register 0x114a bit3; native
observation does not reproduce this state-changing side effect.

Gauge and thermistor compensation update
---------------------------------------

See GAUGE.rst for the native bounded current observer, exact active-versus-sysfs
CAR_TUNE distinction, synthetic integration results and the recovered NTC
current-compensation path. The additional pure thermistor converter is checked
against original ARM64 execution. It is not a valid native battery-temperature
provider: fresh paired NTC/BIF sampling, separate BATON/TDET ownership and live
calibration remain required. Charging enable remains unavailable.
