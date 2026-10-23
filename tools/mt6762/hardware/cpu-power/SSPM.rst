Bounded native SSPM transport
============================

``bsd/dev/mt6762_sspm.c`` adds an active PLATFORM liveness transaction to the
readback-only CPU milestone. No native CPU initialization command, performance
vote, voltage write, reset, firmware load or direct PLL fallback is implemented.
No physical device has executed this path.

Admission
---------

The common version-1 native handoff and ``sspm-mailbox-owned=1`` are mandatory.
This property requires exclusive AP ownership of mailbox-0 PLATFORM and CPU
pins, their data slots and acknowledgement consumption, with the previous AP
senders and interrupt handler quiesced. It does not transfer SSPM's ownership
of clocks or regulators. The driver separately checks mailbox0 GIC INTID237
(actual DT SPI205) is disabled and inactive, and rejects inherited IN/OUT
traffic on either owned pin. No inherited status is cleared or reset.
The IRQ check repeats before every active transaction.

A physical handoff additionally requires ``sspm-firmware-preserved=1``.
This is an explicit loader assertion that the active firmware image, its actual
dynamic shared-memory allocation and EMI access survive, and that XNU's page
allocator cannot reclaim those ranges. It is not inferred from mailbox state
or a heartbeat. No physical loader currently establishes this assertion. Only
an explicitly labeled ``lab-fixture=1`` bypasses it: the synthetic model has
no resident firmware or shared DRAM image, and declares no fabricated range.

Only 0x10450000..0x104500ff data and 0x10451000..0x10451007 control are mapped.
The exact stock ``mt6765_send_pintable`` has 80-byte descriptors. PLATFORM's
packed descriptor is 0x10600 at 0xffffff8009846a70: mailbox0, slot0, three
words, return data. CPU's descriptor is 0x130818 at 0xffffff8009846ac0:
mailbox0, slot3, four words, return data. The latter is interpreted by host
transport tests; native code never sends a CPU command. ``extract_sspm.py``
reproduces these bounded records from the known Image digest.

Transaction and liveness
------------------------

The exact native core in ``mt6762_sspm_protocol.h`` validates ownership, pin
and message size. It rejects pending traffic, writes only the selected pin's
slots, orders the payload before its single-bit IN doorbell, and polls the
matching OUT acknowledgement with a hard bound. It reads the reply, requires
the matching IN bit consumed, clears only its OUT W1C bit, and verifies that
clear. A reply with an unconsumed IN bit is not accepted. Other channels'
status is preserved. Failed operations leave the caller's reply unchanged.
Timeout, bus failure, stuck status or ownership conflict latches a fault;
there is no automatic stale-ack clearing, reset or retry after a fault.

The native attachment sends the stock PLATFORM command 0xDEAD with two zero
arguments, avoiding stock's uninitialized extra words. Each probe has a
100-millisecond software polling limit (not a hardware latency guarantee).
That bound assumes MMIO transactions return; platform handling for an external
abort or hung interconnect is not provided by this polling core.
A nonzero acknowledged reply is stock's alive indication. Probes repeat every
five seconds while the transport remains healthy, and the passive
``mt6762_sspm_alive_recent`` API expires success after ten seconds. A
PLATFORM reply proves neither CPU-DVFS initialization nor calibration,
thermal policy, rail readiness or firmware-image compatibility.

The existing stock alive sysfs attribute also actively sends this command.
It has not been read under the passive stock-ADB authorization.

What still blocks a performance vote
------------------------------------

There is no compiled stock GET_FREQ/GET_VOLT IPI query to substitute for the
shared-table and hardware readbacks. Commands 0/1 initialize CPU-DVFS tables
and state; they must not be replayed into an active inherited controller.
A real loader must establish which firmware image/ABI is active and whether
its CPU-DVFS controller is already initialized, preserve or explicitly
initialize calibrated tables, and transfer the AP scheduler/PPM/EEM/hotplug
interfaces coherently. The source packet format alone cannot establish this.
SSPM firmware memory must also survive the OS handoff: prior LK boot records
reserve 0x7f700000..0x7f7bffff (0xc0000 bytes) as SSPM-reserved. Separately,
the stock DT requests a dynamically allocated 0x510000-byte SSPM shared region
aligned to 0x10000 within 0x40000000..0x9fffffff. The actual current allocation,
firmware image identity and EMI permissions must be discovered and preserved;
the prior LK range does not identify that Linux shared-memory allocation.

Before any performance change, native policy also needs verified live EEM
voltages, CPU/CCI mapping, silicon bin, calibrated thermal/current budgets,
all cluster online states and an independently reliable failure response.
A future bounded vote can compare requested and achieved index, actual
PLL/divider configuration and shared VPROC/VSRAM settings. It need not invent
a sequence acknowledgement that does not exist. An unsolicited PLATFORM
heartbeat or a stationary shared index is insufficient transition proof.
``dvfs_control_ready`` consequently remains false.

Validation and laboratory limits
-------------------------------

``test.sh`` tests the exact native core with injected MMIO callbacks, including
both pin layouts, stale ownership, timeout, late acknowledgements, input not
consumed, W1C preservation, and read/write faults. Outputs are unchanged on
failure, and a latched fault prevents further register access.

The opt-in QEMU fixture in ``hw/misc/mt6762_sspm_lab.c`` models only mailbox-0
storage/doorbells and an immediate synthetic PLATFORM reply. It has no SSPM
firmware, CPU-DVFS execution, rail/clock model, notification ring or interrupt
delivery. ``tests/mt6762/test_lab_sspm.py`` independently passes register-level
positive/fault/default-absence tests and confirms that CPU commands receive
no fabricated success. Actual eight-core XNU build8 guest boots reject timeout, stuck ACK, unconsumed
input, stale ACK/input and wrong-channel ACK; DEAD returns alive=0. Inherited
stale cases issue zero writes. The wrong-ACK three-second probe initially ended
before PID1 observation; its eight-second rerun passed. Exact guest/model hashes
and counters are in ``evidence/native-sspm-build8-faults.json``. Successful
laboratory liveness is not physical-device validation.

A separate physical memory-preservation admission contract
--------------------------------------------------------

``sspm-mailbox-owned`` alone cannot establish firmware-memory preservation. A
physical handoff needs a separate ``sspm-firmware-preserved`` capability with
actual firmware and shared-memory ranges, allocator exclusions covering them,
verified current EMI permissions, and active firmware identity. The actual
0x510000-byte Linux shared allocation must be obtained from the active boot;
its address is not fixed by DT and cannot be copied from the LK 0xc0000 range.
Native boot reservations must exclude both from allocator/reclamation and
from loader placement. A boolean alone is insufficient validation. Laboratory
fixtures have no firmware DRAM and need an explicit synthetic exception, never
a fabricated physical reservation. The current mailbox-only API does not
validate these ranges and is therefore not admitted for physical firmware use.
