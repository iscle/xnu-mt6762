Temporary LK loading: source audit
=================================

Scope and conclusion
--------------------

This audit reads the existing mtkclient checkout at commit
``fa97df7df41140e60f215f24eea82cb46faf9ff0`` and the supplied MT6765 preloader BSP.
It performs no USB/device commands, flash operations, payload execution, or
binary reverse engineering. The exact dumped preloader command-dispatch audit
is a separate task; BSP defaults alone cannot establish the phone's behavior.

A concrete RAM-only image-transfer path exists in the BSP. The existing
mtkclient CLI does not provide a complete, validated patched-LK bootstrap that
preserves the currently running stock LK/ATF/GZ state. Generic DA memory writes
and jumps are insufficient evidence of that contract.

Existing mtkclient behavior
---------------------------

``mtkclient/Library/mtk_main.py:530`` implements ``plstage``. For this chip family
the configured payload address is0x40200000 (``config/brom_config.py:1397``).
The default payload is the supplied ``payloads/pl.bin``. A differently named
``--pl`` input is passed through the generic preloader-security patcher before
being uploaded. Thus supplying a patched LK file as ``--pl`` would neither
preserve its bytes by contract nor place it at LK's linked0x48000000 address.

When an explicit preloader filename is configured, the command disables the
watchdog, parses/reloads that preloader with SEND_DA/JUMP_DA, reconnects, and
then handles ``--startpartition``. This is a new preloader execution, not a
continuation of an existing LK context. The line that would send replacement
partition data is commented out at ``mtk_main.py:600``. The active code sends
only JUMP_TO_PARTITION. With no explicit preloader filename, this option does
not enter that branch and the generic stage payload is uploaded instead.

``Library/mtk_preloader.py:491`` sends command0x71 and a64-byte partition name;
it accepts any returned status<=0xff, even though the BSP distinguishes status0
from status1. ``send_partition_data`` at501 sends command0x70, name, length,
bytes and checksum, but does not read back RAM or obtain a final checksum
acknowledgement. The checksum helper at26 handles trailing bytes incorrectly
for lengths congruent1 or3 modulo4; a future transfer must reject unsupported
lengths or correct and test that helper. These routines are not a ready
end-to-end verification protocol.

``da peek``/``da poke`` dispatch to the running download agent's extensions
(``Library/DA/mtk_da_handler.py:1195`` and1230). XFlash commands0x0f0001 and
0x0f0003 transfer memory; they do not establish a boot register context, clean
instruction caches, supply LK boot arguments, or arrange an ATF transition.
The XFlash ``boot_to`` function at ``xflash/xflash_lib.py:285`` sends only an
address and size followed by the payload. It expects a DA protocol status or
SYNC token afterward; this return convention is not a stock-LK startup ABI.
The legacy ``boot_to`` method is unimplemented. The stage2 client has a jump
primitive but no general CLI jump operation or documented LK context contract.

The local source inventory contains stage1 payload sources and their Makefile,
but no matching source/build rule for ``pl.bin``, ``stage2.bin`` or ``da_x.bin``.
Their existence does not prove preservation of machine state. This audit does
not execute or infer their internals from their filenames.

Selected BSP's RAM-image protocol
--------------------------------

Paths below are relative to
``vendor/mediatek/proprietary/bootable/bootloader/preloader/platform/mt6765``.

``default.mak:111`` sets ``CFG_PRELOADER_AS_DA=1``; special TINY/SLT/CTP/
DUMMY_AP modes override it. ``src/core/inc/download.h:82`` and the dispatch
switch in ``src/core/download.c:1170`` guard commands0x70/0x71 with this flag.

``usbdl_init_image`` at524 establishes these RAM destinations, not flash
partition writes: LK at ``CFG_UBOOT_MEMADDR-512`` with a9MiB limit; logo at
0x4e900000-512 with a6MiB limit; boot at0x40080000 with a64MiB limit; and tee1
via a temporary buffer with a512KiB limit. ``CFG_UBOOT_MEMADDR`` defaults to
0x48000000. The512-byte LK image header belongs at0x47fffe00 and code begins
at0x48000000.

``usbdl_send_image`` at618 receives the named image into RAM, computes an
additive little-endian32-bit checksum plus any remaining bytes, and compares
the supplied checksum. The final acknowledgement is commented out. The
unknown-name/invalid-length path also does not cleanly reject the transfer:
it can retain address0 and status0. A future host must enforce the known name,
address, length and actual RAM readback itself. For tee1 the routine copies
ATF and optional ATF-DRAM/TEE subimages to their specified locations; it does
not implement the normal complete GZ image-loading sequence.

``usbdl_boot_image`` at573 performs trustzone pre-init, sets FASTBOOT mode,
calls the stock ``platform_set_boot_args``, performs trustzone post-init, and
selects the stock ATAG/boot_arg structure. Name ``lk`` calls ``bldr_jump``
directly. Name ``tee1`` calls ``bldr_jump64`` using the LK entry as the eventual
nonsecure target. That function may redirect through GZ, then invokes
``trustzone_jump`` to populate BL31 arguments and call ``jumparch64``.

The ordinary main path calls the USB handshake before ``bldr_load_images``
(``src/core/main.c:1243`` versus1269). Therefore reaching the USB command loop
does not establish that LK, ATF, TEE or GZ have already been loaded. Normal
ATF-enabled boot uses ``bldr_jump64`` at1302; the direct ``lk`` command is not
equivalent to that path. ``usbdl_jump_da`` separately constructs a DownloadArg
with SKIP_PLL_INIT/SKIP_EMI_INIT flags, invalidates/disables I-cache and disables
SMP; these DA arguments are not LK boot arguments.

Precise prerequisites for a future RAM-only trial
------------------------------------------------

1. Confirm command0x70/0x71 implementations and selected config in the exact
   stock preloader, including destination addresses and the ATF/GZ branch.
2. Establish which firmware images and preloader data structures exist in the
   selected entry mode. Do not assume surviving DRAM content is valid state.
3. Select a transfer route that preserves exact patched LK bytes and its
   partition-header placement; enforce bounded sizes and verify RAM readback.
4. Establish the complete normal boot chain, boot arguments, exception level,
   security state, cache/MMU state, reservations and watchdog behavior before
   transferring control. The preloader's ``tee1`` command can provide part of
   this contract only when its firmware prerequisites are actually satisfied.
5. Demonstrate return to fastboot from the RAM-loaded stock LK before combining
   that change with the XNU diagnostic. Persistent LK/TEE/preloader writes are
   outside this route and were not performed or authorized by this audit.

This establishes a source-supported candidate route, with concrete missing
evidence. It does not establish that an immediate ``plstage --startpartition
lk`` invocation is a safe or functional solution to the observed LK panic.

Independent exact-image result
------------------------------

The separate firmware audit subsequently found that the dumped stock preloader
does not dispatch commands0x70/0x71. For stock SHA256
``7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674``,
the Thumb command loop at0x202c90 echoes the command at0x202cae, handles the
0xc4..0xe7 range and selected other commands, then returns to the loop for
0x70/0x71. Thus the BSP-only RAM-image candidate is unavailable in that exact
preloader. This finding was provided by the independent firmware agent; this
document's own investigation remained source-only. A newly proven bootstrap
or patched preloader/DA bridge would be required, with all preceding state
requirements still unresolved. There is no supported ready-to-run RAM-LK
command established by the current tools.
