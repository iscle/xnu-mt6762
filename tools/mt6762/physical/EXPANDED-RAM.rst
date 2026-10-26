Captured six-GiB DRAM map
========================

The runtime LK FDT reports one bank at0x40000000 with size0x180000000:
6GiB installed, ending at0x1c0000000. The earlier512MiB XNU limit was a
diagnostic policy, not the phone's installed memory capacity.

``build_payload.py --expand-memory`` retains the validated low-address base
and extends its window within that bank, stopping before every firmware
reservation, possible dynamic-allocation range, framebuffer, runtime FDT,
and live source Image. It additionally bounds the end by the CPU's advertised
physical address width and rounds down to2MiB. No disjoint banks are joined.
The original512MiB admission remains required, leaving a low-address region
for peripheral DMA buffers. Native I2C DMA allocation is constrained below4GiB.

With the captured map the accepted window is0xd0000000..0x1bfe00000,
size0xefe00000 (3,838MiB). The top firmware page at0x1bffff000 is excluded.
Lower exclusions include broad Linux dynamic allocation constraints; they
do not mean that firmware permanently consumes all the remaining RAM.
Reclaiming those ranges needs separate ownership evidence. This change does
not yet give XNU all6GiB.

Image17/kernel33 replayed the exact captured FDT in a6GiB Cortex-A53 QEMU
instance and reached diagnostic PID1 with both205-case IIG checks. The loader
patches boot_args and ADT with the same expanded size; captured runtime
boot_args confirmed that size.16KiB VM pages over4KiB hardware
translations, native captured-profile display and PWM dim/restore all passed.
The framebuffer was visually reviewed and shows the completed PID1 checks.

Image16 adds an optional passive158-register peripheral snapshot using the
same expansion path. Its first emulator run faulted on an unmodelled PLL
register at0x1000c26c before RAM selection. That run is a failed emulator
boot, not physical failure evidence or a passing end-to-end test. The passive
reader has separate host checks and a stock-register audit. It grants no
touch, PMIC, clock, storage or DMA ownership.

Physical capture15 subsequently recovered the matching Image16 record with
all158 entries read twice. XNU reached PID1 and passed both205-case checks.
Runtime boot_args and gPhysSize both report0xefe00000 bytes. The native PWM
driver recorded duty256 then restoration to1023. This establishes physical
boot with the expanded map, not an exhaustive RAM stress test or visually
confirmed brightness response. The retained log SHA256 is
f1d6b248818c9e164a683d475fb2523c0a4142eec1949913256c3e920f12fb9f.

Image18/kernel35 is the following physical touch trial. It revalidates the
captured124.8MHz I2C parent, pad/reset/EINT state and idle I2C/APDMA before
granting I2C0 alone. The kernel repeats admission, configures100kHz timing,
requires version0007 from the stock combined FIFO command, and checks one
32-byte DMA receive before continuous polling. The private DMA page lies below
4GiB and has leading/trailing canaries. Polling uses scheduled sleeps.
This does not assert measured regulator voltage. PMIC rails, touch reset and
firmware remain unchanged. Physical touch operation is awaiting capture16.

An opt-in watchdog refresh worker has also been compiled but is disabled in
Image18. It accepts only the measured MODE/LENGTH/request-routing profile,
issues the stock RESTART=0x1971 store and never reconfigures the watchdog.
Its physical sustained-refresh behavior remains unvalidated.

The helper tools and test manifests contain no firmware or Apple userspace.
The normal-boot image is a diagnostic, not a usable iOS desktop image.
