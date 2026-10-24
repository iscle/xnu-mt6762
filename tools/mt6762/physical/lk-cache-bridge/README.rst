Offline fastboot image-cache bridge
==================================

This is a concrete source fix for the observed exact-LK fastboot NULL-cache
panic. It is **not a deployable LK image or a validated physical boot path**.
No phone command, partition write, security-state change or LK image mutation
is performed by these tools.

The bridge changes only the behavior of the original call at0x4801dede in
``cmd_boot``. The four-byte replacement BL is pinned to original bytes
``19f02bf8`` and the complete dumped LK SHA256. Normal boot callsites remain
unchanged. Its assembly wrapper captures the downloaded pointer from r7 and
byte count from r9, validates the image before allocating, calls the exact
existing cache allocator, and copies the complete image into that owned buffer.
It then restores the caller's registers/stack and tail-calls the original
decapsulator, whose cached lookup now succeeds. The allocator and its free
callback retain the same ownership as the normal verified-image loading path.

On admission/allocation failure, the wrapper sends fastboot FAIL and branches
to the original handler cleanup at0x4801df82. That cleanup frees the handler's
already allocated header and unwinds its frame. It does not return a false
success into the remaining boot code. The bridge makes no storage, MMIO,
authentication-policy, unlock or verity-status calls.

Admission contract
------------------

The source must be the exact fixed fastboot transfer base0x48b00000 and its
reported byte count must be1660..128MiB. The header must have Android magic,
version2, size1660 and a supported power-of-two page size. The kernel and DTB
must be nonempty; a second-stage executable is rejected. Every serialized
component and its padding must fit the download without arithmetic wrap; a
nonempty recovery DTBO must have its exact64-bit file offset. The last component
must end exactly at download size. This deliberately accepts the diagnostic
boot-v2 format and rejects unsupported layouts/trailing data.

These checks precede cache allocation. Original LK continues to own its
subsequent destination-address checks, DT handling and transfer. Passing this
bridge is not proof those later stages or the physical XNU payload work.

Build and tests
---------------

Requires an existing LLVM clang/lld capable of arm-none-eabi, Python pyelftools,
Capstone (for the separate audit), and Unicorn. No dependency installation is
performed::

  python3 build.py --lk /path/to/lk.bin \
    --llvm-bin /path/to/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin \
    --load-address 0x48200000 --out /tmp/lk-cache-bridge
  python3 test_bridge.py --lk /path/to/lk.bin \
    --boot /path/to/mt6762-xnu-diagnostic-boot.img \
    --artifacts /tmp/lk-cache-bridge -v

The example0x48200000 is only a model/linker coordinate; its physical ownership
is **unverified and it may overlap the running LK heap**. Do not inject there
based on these tests.

The compiled Thumb blob was419bytes with the supplied NDK clang. Seven tests
passed using the actual build4 diagnostic image. Unicorn executes the compiled
shim, the patched original call, original cache name lookup/allocation logic,
and the original decapsulator through its successful cached-header branch.
Only external heap allocation, memcpy, fastboot response, verbosity query and
final free are mocked. Tests verify:

* Correct full-byte copy and cache pointer/size with no response failure.
* Original cache replacement frees the prior buffer through its callback.
* Null allocation, including replacement, produces FAIL and original cleanup.
* Thirteen malformed header/bounds/source cases never allocate or copy.
* Success preserves r4..r11, SP and caller LR; rejection executes the original
  frame unwind. External call stacks remain8-byte aligned.
* BL encoding reproduces the original exact call and rejects invalid ranges.

No actual heap allocator, cache maintenance, peripheral, storage I/O, full LK
boot or XNU execution is proved by this CPU model.

Deployment boundary
-------------------

``build.py`` emits only an ELF, injectable original-code blob and guarded patch
manifest. It intentionally emits no full patched LK partition. The input's
partition header declares payload length0xac5bc; the embedded FDT begins later
at file0xad850. Appending a stub requires changing the loaded extent and proving
its relationship to data/BSS, embedded DT and live allocations. This proof is
absent. A linker address inside unused-looking partition padding does not mean
LK loads or safely executes it.

Any future RAM-only integration must independently establish an owned executable
range, install the blob there, compare the callsite preimage, apply only that
four-byte BL, perform required data/instruction cache maintenance and establish
a supported transfer into that running LK. Runtime placement and transport are
not part of this bridge. Flashing or overwriting persistent LK is not a fallback
implemented by this package.
