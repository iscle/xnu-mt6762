Temporary Android boot-v2 container
==================================

bootimg.py creates an Android boot container from an explicit kernel payload
and ramdisk, preserving the supplied stock header metadata and DTB table. It
does not invoke fastboot, reboot, flash, unlock, or otherwise contact a phone.
The root physical-loader producer must supply the actual hardware handoff;
wrapping the QEMU trampoline would not establish a physical boot path.

Example file-only packaging, after preparing the physical payload:

::

    python3 bootimg.py pack \
      --template /home/iscle/Documents/mini_iphone_dump_2/boot.bin \
      --kernel /path/to/physical-aarch64-image --gzip-kernel \
      --ramdisk /path/to/explicit-ramdisk \
      --output /path/to/new-temporary-boot.img

Omit --gzip-kernel when the kernel input is already one complete gzip stream.
The pack command checks for the ARM64 Image header after bounded decompression.
That identifies the container convention, not the payload's functional safety
or hardware readiness. The ramdisk is opaque caller-supplied data; no stock
Android ramdisk is silently substituted. Address/cmdline changes require
explicit options. The pack command retains the stock 64-bit bootopt in the
first command-line field and checks 512 KiB kernel-address alignment. Existing
output image or manifest paths are rejected.

An adjacent JSON manifest records input/output hashes, component offsets,
addresses, decompressed kernel size/hash, preserved DTB table and omitted old
trailer. The output is labelled unsigned and not hardware validated. Header
SHA1 is Android's image identifier, not a signature or authentication claim.
No AVB footer, vbmeta signature or forged signature is created.

Exact stock structure
---------------------

The supplied boot.bin is a 32 MiB partition dump with Android header version 2,
a 1660-byte header and 2048-byte pages. Its compressed kernel is 10,915,906 bytes
at image offset 0x800, load address 0x40080000; its decompressed Image is 25,714,688
bytes. The 1,620,262-byte ramdisk loads at 0x51b00000. Tags and DTB addresses are
both 0x47880000. Command line is ``bootopt=64S3,32N2,64N2 buildvariant=user``.
There is no second-stage or recovery-DTBO component.

The 109,780-byte DTB section at offset 0xbf6000 is an Android DT table with one
109,716-byte FDT at table offset 64. The packer validates table/entry/FDT bounds
and retains the table bytes exactly. Payload padding ends at 0xc11000. The old
partition trailer contains an actual AVB footer/vbmeta and is intentionally
excluded from any replacement image.

The stock ID is 5b1326f1715379ddb574eb332e0b78e52724737c. It is SHA1 over kernel
bytes plus little-endian 32-bit size, ramdisk bytes plus size, second bytes plus
size, recovery DTBO bytes plus size and DTB-table bytes plus size, including
size 0 for absent sections. Twelve zero bytes pad the 20-byte digest into the
32-byte ID field. The supplied
BSP system/core/mkbootimg/mkbootimg.py independently reproduces the exact stock
payload and identifier; the parser/repacker roundtrip matches it byte for byte.

LK path and limits
------------------

bootimg-stock-evidence.json retains bounded static evidence and hashes. The
dumped LK has a 512-byte MediaTek partition header and relocates its executable
to 0x48000000. At VA 0x4801cf96 its fastboot initialization loads 0x08000000, stores
the download limit and formats the published max-download-size value. At
VA 0x4801d244 it registers ``boot`` with Thumb handler 0x4801deb5 and the secure /
unlocked flags. The handler allocates/copies the 1660-byte header and follows
the supplied BSP's load_bootinfo_bootimg path. These are static observations,
not a successful physical fastboot boot test or current getvar result.

The selected k62v1_64_bsp rules set scratch at 0x48b00000 with 128 MiB capacity,
matching the dumped initialization immediate. The packer conservatively caps
the complete output at 128 MiB. This is the default command buffer limit; any
runtime mode or transport differences still require live verification.

BSP cmd_boot checks kernel/ramdisk ranges against each other, DRAM, LK memory
and the download region. It marks the downloaded image loaded, copies the
ramdisk to its declared address, appends boot parameters, stops USB, refreshes
the watchdog and enters boot_linux. bootopt selects the 64-bit path, which
decompresses the kernel from the downloaded payload into the declared kernel
address. That address must have 512 KiB alignment. The selected MT6765 platform
defines 120 MiB decompression capacity (0x07800000); a stale 28 MiB comment in
mt_boot.c is not the current configuration. The dumped LK's allocation path
contains the same 120 MiB immediate; this audit did not fully prove every actual
decompressor bound. The packer's gzip limit follows that selected capacity.

For boot-v2, load_bootinfo_bootimg locates the DT table after all page-aligned
payload sections and selects the first FDT after its table entries. The later
64-bit jump passes the tags/FDT address through LK's existing secure transition.
The loader must inspect the actual handoff, memory reservations, initrd range,
display and device state; header addresses alone do not establish ownership.
Normal LK may also update the DT from platform information and overlays.

The command is compiled into this dump and requires unlock permission. The
user reports that the bootloader is now unlocked. Image authentication behavior,
available DRAM/overlap constraints, actual entry state and unsigned temporary
payload acceptance remain physical-validation requirements. This packer does
not claim to bypass them or to reproduce a trusted boot signature.

Validation and scope
--------------------

Eight tests cover malformed headers/components/IDs, DT/FDT bounds, recovery
offsets, full metadata roundtrip, bounded single-stream gzip, exact stock
roundtrip, actual CLI creation/rejection guards and independent BSP mkbootimg
equivalence. Tests operate on local
files only. REA's firmware scan was unavailable because its caller-supplied
Binwalk path is not configured; no provider was installed. The retained binary
observations came from bounded Python/Capstone decoding and explicit PIC/GOT
address resolution, and are not presented as REA runtime Evidence.
