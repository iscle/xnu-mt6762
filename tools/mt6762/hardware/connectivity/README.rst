MT6762 connectivity: offline parsers and passive observations
===========================================================

This package does not start Wi-Fi. It validates retained stock artifacts and
parses bounded observations before a future native backend. No function performs
MMIO, allocation, firmware download, DMA, radio commands, or phone access.
There is no kernel/init integration. Original firmware and calibration remain
private local inputs, never repository payloads.

``conn_decode.c/.h`` is freestanding C99, with no libc dependencies. All reads use
bounded byte decoding, avoiding alignment and host endian assumptions. Failed
calls leave the caller's output unchanged. The core supports:

* Actual CONNAC common tail (36 bytes), up to 16 region tails (40 bytes), payload
  bounds, device-address overflow/overlap, the observed uncompressed feature
  shapes, and bounded release-info TLVs. Device addresses are firmware address
  space, never permissions or destinations for host writes.
* WMT 28-byte patch and 48-byte ROM/RAM metadata headers, exact ALPS signature
  and timestamp shape. HW/SW fields are reported big endian, address/type fields
  retain their raw little-endian representation. CRC fields remain opaque.
* The exact phone's 2050-byte WIFI calibration file envelope: 2048-byte BSP
  structure, versions 1/8 and a structurally valid unicast nonzero address,
  plus two uninterpreted trailer bytes. No address/calibration bytes are returned.
* Project passive-record version 1, specified in ``conn_decode.h``. It rejects
  malformed sizes, versions, reserved fields, duplicate/unknown addresses,
  invalid widths, backward time and unbounded snapshot intervals. Only valid
  stable paired observations contribute. Classification is default-off.

Structural acceptance is separate from authenticity. ``validate.py`` first
checks exact size and SHA-256 against ``stock-profile.json`` and then calls the
compiled C core. The profile pins the dumped vendor modules, configuration and
four WLAN/common firmware files, plus this phone's complete calibration hash.
There is no CLI override allowing a different hash profile. This does not prove
an image matches a live ADIE/ECO, authenticate its vendor signature, implement
firmware CRC algorithms, or establish radio/regulatory calibration semantics.
It also does not claim the manifest is an exhaustive future cold-start bundle.

Usage (all paths are explicit local inputs)::

    python3 validate.py --artifacts /private/stock-artifacts \
      --calibration /private/WIFI
    python3 validate.py --peripherals /private/peripherals-result.json --survey
    python3 validate.py --record /private/conn-record.bin --survey
    python3 validate.py --display /private/display.bin \
      --display-identity EXPECTED_64_HEX_LOADER_IDENTITY
    python3 -m unittest discover -s . -p 'test_*.py' -v

A host C compiler builds the shared parser into a temporary directory; nothing is
installed. ``CC`` can choose a host compiler. A future kernel can compile the C
core directly and separately require cryptographic artifact verification before
using any parsed payload. The Python command does not dump input bytes, addresses,
SSID or credentials; its firmware target addresses are not the private WLAN MAC.

State evidence and limits
-------------------------

The passive format has no hardware grant flags. ``POWER_BITS_READY`` means only
that the modeled SPM power/reset/isolation and infra protection bits matched in
a stable pair. It is not authorization to read powered CONN registers or perform
DMA. Even that result leaves rail state, clock accessibility, ADIE/ECO, reset
ownership, EMI/MPU, DMA routing/cache maintenance and firmware matching unresolved.
Default ``survey_enabled=0`` decodes observations but returns unknown power state.

The candidate address list is a decoder vocabulary, NOT a physical read allowlist.
An acquisition implementation must review each new read against the shipped
module and current power state. It contains no 0x180xxxxx connectivity registers.
The stock function ``consys_check_reg_readable`` is actively mutating: it writes
0x30000, barriers/delays, then tests clock bits. It must not be called a passive
probe or used here.

Captured display records are decoded by the existing strict display ABI decoder
with a separately supplied expected loader identity. Only the final pass remains
in that record: this package does not duplicate it into an invented stable pair,
merge asynchronous display/peripheral samples, or treat display's SPM control
0x1000630c as connectivity's different control at 0x1000632c. External identity
must be verified against the frozen loader manifest; matching a caller-provided
identity is not independent proof of provenance or freshness.

Capture40's display power statuses are both 0x434c. CONN bit1 is clear in each,
so connectivity was off at that recorded sample. This says nothing about later
power state. The peripheral record contributes only GPIO 0x100053f0 from the
connectivity vocabulary; the required control/protection/clock/rail state remains
missing. See ``validation-evidence.json``. No further device action was taken.

Source basis
------------

Private exact firmware audit:
``hardware/hakios-migration-20261026/wifi-native/evidence.json`` in the workspace.
Its stock modules are 4.19.191; their AXI symbols, MT6765 operations table and
bounded relocation-annotated disassembly corroborate this platform. The supplied
BSP is a reference, not an assertion of full source equivalence:

* ``vendor/mediatek/kernel_modules/connectivity/wlan/core/gen4m/include/chips/fw_dl.h``
  lines 121-142 and ``chips/common/fw_dl.c`` lines 1602-1664, 1993-2048:
  CONNAC tail/release formats and download interpretation.
* ``common/common_main/core/include/wmt_core.h`` lines 427-443 and
  ``core/wmt_ic_soc.c`` lines 3260-3305, 3550-3650: WMT 28/48-byte formats.
* ``wlan/core/gen4m/include/CFG_Wifi_File.h`` line 479 onward: calibration envelope.
* ``common/common_main/platform/include/mt6765.h`` lines 45-100, 130-142:
  pinmux, SPM/infra offsets and CONN ack bit1. Shipped ``wmt_drv.ko`` separately
  confirms the selected platform and the active readability-test behavior.
* ``tools/mt6762/physical/display_probe.h`` records SPM 0x10006180/184/30c;
  ``display_record.py`` validates the existing build-bound format.

Next integration should retain the existing Qualcomm exclusion. A MediaTek
backend must own the cold-start power/WMT/STP flow and separate CONNAC AXI DMA
interface, then attach ``hakios_sta_ops`` and ``hakios_net_link``. The Qualcomm
ath11k bus/QRTR/SMMU implementation is not this radio's transport. Actual firmware
selection still requires live ADIE/ECO and per-phone calibration validation.
