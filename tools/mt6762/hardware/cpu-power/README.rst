CPU clocks, shared PMIC rails and DVFS audit
==========================================

Status
------

This source-only package selects and checks nominal stock C62 OPPs offline.
It contains no PLL/PMIC/MMIO writes. NATIVE.rst documents the subsequently
added XNU readback module; DVFS control remains disabled.
Read-only stock Android observations and exact stock kernel evidence establish
frequency limits and the selected nominal table. Native clock/voltage changes,
SSPM coordination, EEM calibration and thermal limits remain unvalidated.

Run ./test.sh for host validation. No binaries are included; temporary test
executables are removed. The tests check real-table maximum frequencies,
thermal/policy caps, no feasible OPP, shared-rail demand, selector rounding and
SSPM request encoding. They do not test hardware transitions.

Observed hardware policy and selected bin
----------------------------------------

Live policy0 applies to CPUs0-3: 900000..2001000kHz,16 points. policy4 applies
to CPUs4-7: 400000..1500000kHz,16 points. The reported current sample was
1484000kHz and400000kHz respectively. cpuinfo_cur_freq and governor readback
are denied, so those samples are software reports, not measured PLL output.
The generic CPU DT maxima2301000/1800000kHz do not describe this unit's limits.

The exact stock selector at0xffffff800867c108 reads nvmem cells
 efuse_segment_cell and efuse_ly_cell. Its printf format at0xffffff800940a41f
is eight comma-separated integers: level,turbo,segment,LY,then four slew rates.
At0xffffff800867c330..340 the selected level is passed as arg1,segment as arg3,
LY as arg4 and833 as all four rate arguments. Bounded expdb records report
4,0,1,0,833,833,833,833. Thus the recorded boot selects level4,C62,segment1,LY0.
The live frequency vectors match the corresponding exact ELF arrays. This
resolves the C62 versus C62LY nominal-table ambiguity. It does not establish
that EEM left runtime voltage calibration unchanged.

The extracted stock tables reside at these VAs:

* L level4: 0xffffff8009814620; CPUs0-3.
* LL level4: 0xffffff8009814ba0; CPUs4-7.
* CCI level4: 0xffffff8009815120; coherent interconnect.

Each has16 pairs of little-endian u32 frequency_kHz and voltage_10uV.
extract_opp.py re-extracts them from the supplied Image/ELF, verifies the Image
hash, and saves only exact technical bin records with expdb offsets. All11
stock candidate levels are recorded as evidence; only verified level4 is
used in the portable selector.

Nominal table (not runtime measured voltage)
-------------------------------------------

==== ============ ============= ============ =========== ============
Idx  CPU0-3 kHz   CPU4-7 kHz    CCI kHz      L/CCI uV    LL uV
==== ============ ============= ============ =========== ============
0    2001000      1500000       1048000      1118750     1118750
1    1961000      1429000       997000       1068750     1068750
2    1927000      1367000       953000       1025000     1025000
3    1897000      1314000       915000       987500      987500
4    1868000      1261000       877000       950000      950000
5    1838000      1208000       839000       912500      912500
6    1809000      1155000       801000       875000      875000
7    1779000      1102000       763000       837500      837500
8    1750000      1050000       724000       800000      800000
9    1617000      948000        658000       768750      768750
10   1484000      846000        592000       737500      737500
11   1351000      745000        525000       706250      706250
12   1218000      643000        459000       675000      675000
13   1085000      542000        392000       643750      643750
14   979000       501000        339000       618750      631250
15   900000       400000        300000       600000      600000
==== ============ ============= ============ =========== ============

mt6762_c62_select chooses the highest table frequency no greater than request,
policy ceiling and thermal ceiling, and no lower than the policy floor. All
limits must be nonzero/known. An impossible request fails without changing
output. This can plan best permitted performance, but does not prove thermal
readiness or authorize voltage writes. CCI has a separate performance demand;
its table index is not assumed equal to either CPU cluster's index.

Shared PMIC rails
-----------------

BSP mach/mt6765/mtk_cpufreq_platform.c cpu_dvfs assigns L,LL andCCI the same
CPU_DVFS_VPROC1 andCPU_DVFS_VSRAM1 supplies. Native policy must aggregate demand
from all three and coordinate transitions. mt6762_c62_shared_voltage computes
the maximum nominal demand across three supplied indices; runtime EEM-adjusted
values must replace nominal data before hardware control.

BSP include/linux/mfd/mt6357/registers.h defines VPROC request selector at
0x14aa mask0x7f shift0 and readback at0x14a2 mask0x7f shift0. VSRAM_PROC request
selector is0x19fa mask0x7f shift0 and readback0x19cc mask0x7f shift8. These are
PMIC addresses transported over PWRAP, not CPU physical MMIO addresses.
Exact stock mt6357_transfer2pmicval at0xffffff800867c564 and transfer2volt
at0xffffff800867c59c implement the linear base518750uV,step6250uV. The DT permits
518750..1312500uV for those regulators, but those broad regulator limits do
not authorize that entire range for the CPU. Portable selector arithmetic
requires an explicit voltage window and rejects upward rounding above its
maximum. In particular1120000uV cannot be represented exactly.

BSP CPU-specific policy constraints are VPROC600000..1120000uV and
VSRAM850000..1120000uV,normal SRAM offset100000uV,maximum rail difference350000uV.
The platform's regulator request allows an extra6250uV for quantization.
BSP sequencing raises VSRAM before VPROC and lowers VPROC before VSRAM in bounded
steps; assertions require VSRAM>=VPROC and difference<=350000uV. Settling uses
ceil(abs(delta_10uV)/833)+5us. Frequencies are raised only after voltage rises
settle and lowered before voltage reduction. These are source requirements,
not verified timing margins for a replacement controller. Live regulator name,
voltage and state reads are permission-denied; no actual rail readback is known.

PLL and CPU clock register dependencies
--------------------------------------

APMIXED base0x1000c000 and MCUCFG base0x10200000 come from BSP and DT.
CPU0-3 uses ARMPLL_L CON1 at0x1000c220 and CKDIV at0x102007a0.
CPU4-7 uses ARMPLL CON1 at0x1000c210 and CKDIV at0x102007a4.
CCI uses CCIPLL CON1 at0x1000c230 and CKDIV at0x102007c0.
PLL PCW is CON1[21:0],postdivider CON1[26:24],PCW-change bit31.
CKDIV[21:17] encodes divider1/2/4 as8/10/11; clock source mux is[10:9].
The inherited boot encoding0 also denotes unity; ``CKDIV0.rst`` corroborates
this specific case with exact preloader instructions and physical capture26.
BSP DDS arithmetic is ((VCO_kHz/1000)<<14)/26,using26MHz reference. Preserve
unrelated register bits. PLL/postdivider settling is20us/1us in this BSP.

Exact method arrays are L_C62 at0xffffff8009815730, LL_C62 at
0xffffff8009815890 andCCI_C62 at0xffffff80098159f0 (16 byte-pairs postdiv,clkdiv).
Their recovered values accompany the C table. BSP set_cur_freq_wrapper raises
divisors before reprogramming VCO and lowers divisors afterward, with frequency
hopping when configured and synchronous DCM handling around changes. These
steps cannot be replaced by writing an arbitrary clock multiplier.

BSP clk-mt6765.c marks ARMPLL_L,ARMPLL,CCIPLL and MAINPLL always-on PLLs.
Their CON0/power offsets are respectively21c/228,20c/218,22c/238,23c/248.
The BSP armpll_control power-up sequence asserts power,waits30us,removes
isolation,waits10us,sets PCW-change,enables PLL,waits20us and releases divider
reset. It is intended for managed cluster power transitions; do not power-cycle
the executing cluster's PLL. CPU hotplug,power domain,coherency and suspend
coordination must be integrated. Live CPU0 idle states are rgidle/WFI andMCDI;
MCDI reports300us latency/1500us residency. Native WFI alone does not implement
that firmware-managed idle path.

Actual stock control path and native sequence
--------------------------------------------

Stock config enables CONFIG_MTK_TINYSYS_SSPM_SUPPORT and hybrid DVFS. DT
mediatek,mt6765-dvfsp maps CSRAM at0x00110c00,size0x1400. The BSP header's
0x00110800 default must not override that DT mapping. The actual stock
cpuhvfs_set_cluster_load_freq at0xffffff800867b4f8 writes scheduler votes at
CSRAM+0x3a4+4*cluster: bits3:0 are OPP index and bits11:4 a1..255 sequence
counter,followed by DSB SY. Cluster IDs map0=L,1=LL,2=CCI. Portable
mt6762_sspm_vote validates and encodes this word but performs no write.
A vote-write function returning0 does not prove SSPM completed the transition.

BSP hybrid initialization uses acknowledged4-word CPU_DVFS IPI messages and
shared tables. It also receives transition logs and accepts EEM voltage updates.
Therefore a native implementation needs this concrete sequence:

1. Preserve/query bootloader PLL,rail,SSPM andCSRAM state; establish a single
   owner for CPU DVFS and validate firmware protocol/version and memory mapping.
2. Validate silicon segment/LY and available OPPs against level4 evidence; obtain
   calibrated EEM voltage data and a valid thermal/power budget. Do not use the
   stock battery temperature getter,which hardcodes25C.
3. Initialize/attach the SSPM mailbox/shared-table protocol with bounded waits,
   validated acknowledgements and transition completion/readback. Do not
   silently fall back to direct PLL control while SSPM still owns the rails.
4. Aggregate both CPU clusters andCCI demands,apply thermal/PPM/current caps,
   submit a sequence-tagged OPP request,and verify actual frequency/voltage.
5. Coordinate scheduler time accounting,DCM,CPU online/offline andsuspend.
   Recover failed transitions without lowering rails beneath any live domain's
   demand. Native error paths must not inherit stock callbacks that report
   success without validating hardware.

Implementing a replacement AP-owned DVFS controller instead would require
verified relinquishment by SSPM and the complete ordered rail/PLL/CCI sequence;
this audit does not establish that ownership handoff. Maximum performance means
the highest currently permitted OPP,not permanently forcing maximum clocks or
enabling every peripheral gate. Peripheral functional clocks must satisfy bus,
panel,storage andDMA timing requirements independently.

Evidence limits
---------------

The read-only ADB collection made no sysfs writes,root requests or reboots.
The bin-selection evidence comes from this device's supplied prior boot log;
current policy vectors corroborate its frequencies. Thermal/PPM/regulator
interfaces were denied. Stock battery temperature25C is fabricated; the
separate nominal NTC conversion in ../power is still uncalibrated. No CPU
performance,thermal stability,rail transition or native suspend acceptance
criterion has been demonstrated under XNU.
