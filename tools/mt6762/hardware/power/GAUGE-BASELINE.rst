Exact-stock fresh gauge coefficient baseline
===========================================

``mt6762_gauge_baseline_from_fdt`` provides a standalone, allocation-free FDT
query for future physical handoff producers and native gauge admission. It
returns R_FG=100 and CAR_TUNE=1000 only after validating the exact captured
board profile. It performs no MMIO, PMIC commands, gauge initialization,
measurement, or ownership grant. Nothing calls it from the current kernel or
physical loader; those integrations remain separate work.

This reproduces fresh startup configuration. It does not reconstruct the last
mutable Android gauge object or independently establish electrical accuracy.
The result must not be interpreted as permission to write a latch or request
an ADC conversion. Hardware configuration, calibration shadows, ownership and
measurement freshness remain separate checks.

Accepted FDT profile
--------------------

The caller supplies an immutable, readable FDT byte span. Version 17, bounded
blocks/reserve map, balanced structure, a single empty-name root, terminated
names/values, property-before-child ordering, maximum depth 64 and maximum
size 512 KiB are required. The exact hierarchy and compatible lists are:

* /: ``mediatek,MT6765``. This is the actual DT name on this MT6762 phone.
* /pwrap@1000d000: ``mediatek,mt6765-pwrap``, followed by ``syscon``.
* /pwrap@1000d000/main_pmic: ``mediatek,mt6357``.
* /pwrap@1000d000/main_pmic/mtk_gauge: ``mediatek,mt6357-gauge``.

Each compatible list must match exactly, including its terminating NUL bytes.
The target must contain exactly one four-byte big-endian ``R_FG_VALUE=10``
and exactly one ``CAR_TUNE_VALUE=100``. Status may be absent or exactly ``ok``
or ``okay`` on each ancestor and the target. Disabled, malformed or duplicate
status is rejected. Duplicate canonical nodes/ancestors, duplicate required
properties and a second MT6357 gauge compatible anywhere in the tree are
rejected, even if that other gauge is disabled. Missing properties and other
coefficient values are refused; no stock or native default is substituted.

On failure the complete result is zero. On success it contains profile version
1, the validated FDT total size, raw DT cells 10/100 and derived coefficients
100/1000. Existing ``mtk_fdt_info`` and its ctypes ABI are unchanged. This is
a separate profile query, not a replacement for RAM/reservation or other
peripheral validation. Unrelated property contents are not interpreted as
hardware configuration by this query.

Original code and executed evidence
----------------------------------

The source Image SHA-256 is
82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b.
The exact stock code establishes this sequence:

* ``mt6357_gauge_probe`` stores a 64-bit pair at
  ffffff8008a8668c: active gauge +110=50, +114=1000.
* ``battery_init`` calls header initialization at ffffff8008a800ac, then
  DT initialization at ffffff8008a800b8 along the successful probe path.
* DT code at ffffff8008a7ccb8 reads ``CAR_TUNE_VALUE`` with multiplier 10;
  ffffff8008a7ccdc copies gm+a0c into active gauge+114.
* DT code at ffffff8008a7cd44 reads ``R_FG_VALUE`` with multiplier 10;
  ffffff8008a7cd68 copies gm+a18 into active gauge+110.
* ``fg_read_dts_val`` at ffffff8008a7e168 performs the scalar read, multiplies
  by its explicit multiplier and stores only on success. Read failure leaves
  the header-initialized value intact.

``replay_gauge_baseline.py`` verifies the Image digest and executes these
original ARM64 blocks and the complete scalar helper in Unicorn. Only OF
scalar reads, profiling and debug-level calls are intercepted. It validates
each retained DT through the actual C query before using its raw cells as
OF-read inputs. The replay records each active-field write and checks every
block reaches its expected endpoint. It is selected-block execution, not
emulation of a complete kernel boot or real hardware.

``evidence/gauge-baseline-replay.json`` pins code, source and DT hashes and
retains the executed results. Both firmware/boot.bin.dtb and capture30's live
runtime.dtb produce (100,1000). Missing-property fixtures produce stock
(50,1000) when R_FG_VALUE is absent; changed cells (11,101) produce (110,1010).
Those fixtures explain why the C query must refuse absent/changed cells.
``evidence/gauge-baseline-disassembly.txt`` retains the exact relevant
initialization/helper instructions and distinct runtime writer paths.

Runtime writers and scope
-------------------------

``info_set`` at ffffff8008a85694 writes active R_FG at
ffffff8008a856e8 for nonzero property 0x33 inputs. The ``r_fg_value`` sysfs
descriptor at ffffff8009887950 is mode 0644 and dispatches to that setter.
Thus historical R_FG cannot be inferred solely from startup inputs.

Property 0x32, ``car_tune_value``, accepts calibration-current inputs 501..1499
and calls ``calculate_car_tune``. Its result is stored at gauge+11c, not active
gauge+114. ``info_get`` likewise returns +11c for this property and +110 for
R_FG. The factory ioctl stores at ffffff8008a888f8/ffffff8008a88920 and the
engineering-command store at ffffff8008a8a16c alter gm+a0c, a separate custom
configuration field. The engineering resistor store at ffffff8008a89a08
alters gm+a18. These stores do not update the active gauge fields.

The retained whole-Image direct B/BL inventory finds one DT initializer call
and 88 calls to ``gauge_set_property``, each with a recovered constant property;
none passes 0x33. Sysfs dispatch is indirect and remains a real runtime writer.
No additional active CAR_TUNE writer was found in the decoded gauge/battery
implementation. This is a bounded static inventory, not a claim that arbitrary
memory corruption or third-party kernel code cannot change an object.

No persistent manufacturing coefficient source is used in the recovered
startup assignment path: the present DT cells are copied into the active
fields after header initialization. A native port can intentionally reproduce
that fresh configuration without recovering historical Android mutations.
PMIC gain/offset/autocalibration already affect raw measurements; their live
configuration still needs to match and must not be applied a second time as
invented software coefficients.

Future integration and validation
---------------------------------

The physical producer can query the immutable live bootloader FDT, record its
identity/profile/raw cells and supply the derived pair. Native admission can
revalidate the same source/profile before accepting those software values.
Neither side should set ``fgauge-owned``, ``pwrap-write-owned`` or a hardware
calibration grant merely because this query succeeds. The five actual words
required by ``mt6762_gauge.c``, gauge clocks, idle latch, exclusive ownership,
coherent acquisition and advancing NTER must be established separately.

``python3 tools/mt6762/hardware/power/test_gauge_baseline.py`` runs nine test
groups covering the profile, every ancestor status, duplicates, malformed and
missing properties, byte order, every accessible-length truncation, invalid
headers/reservations/structure, excessive depth, 1000 deterministic malformed
mutations and both pinned real DTs. Failures leave no coefficients published.
It is also included in the existing power test suite.

To reproduce the saved original-code evidence, run::

  python3 tools/mt6762/hardware/power/replay_gauge_baseline.py \
    --output tools/mt6762/hardware/power/evidence/gauge-baseline-replay.json \
    --disassembly-output tools/mt6762/hardware/power/evidence/gauge-baseline-disassembly.txt

This compiles a temporary host validator and runs offline Unicorn. It never
builds a kernel, connects a phone, changes a partition or runs stock Android.
