Stock preloader normal-continuation audit
========================================

Result
------

The proposed RAM-only continuation is not ready to execute. In the exact stock
preloader, WRITE32 rejects preloader code, stack and LK RAM; the synchronized
download loop has no normal resume command; and the running instruction cache
is not synchronized by WRITE32. An unmodified stock command sequence therefore
cannot install and execute the proposed post-LK-load hook. These are concrete
requirements, not a reason to substitute a persistent LK flash.

Identity and analysis boundary
-----------------------------

Input: supplied ``preloader.bin``, SHA256
``7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674``.
Runtime mapping is VA=file_offset+0x200710, with GFH execution start0x201000.
``audit_preloader_continuation.py`` pins that digest, disassembles bounded
ARM/Thumb ranges, and replays only original register-save/restore and pure
range-check snippets in Unicorn. It creates no payload or RAM patch and never
opens USB. Capstone5.0.7 and Unicorn2.1.4 were used.

REA firmware inspection was attempted but unavailable because the configured
service has no ``REA_BINWALK_COMMAND``. Following the skill's recovery guide,
the audit continued through existing local tools without installation or
configuration changes. The resulting JSON is ordinary offline-tool evidence,
not a claimed REA Evidence record.

Command-loop state and return
-----------------------------

Exact ``usbdl_handler`` starts at0x202bf0. It pushes r4-r7/LR, pushes r8-r11,
and reserves0x3c bytes, for a total0x60-byte frame. Its only normal epilogue is
the initial-handshake timeout path at0x203168: r0=-1, add SP0x3c, pop r8-r11,
pop r4-r7/PC. The replay proves those exact original instructions restore the
saved registers and caller SP/PC for a synthetic valid frame. It does not prove
that any stock command reaches that epilogue after synchronization.

After synchronization the dispatch loop starts at0x202c90. The default branch
at0x202d42 returns there. The actual jump table maps D6 (the host's JUMP_BL)
to0x202d0a, an immediate branch back to the loop; it is not a supported exit.
D4 maps to WRITE32 at0x202dcc, D5 to JUMP_DA at0x202fe8, and D7 to SEND_DA at
0x202e48. The previously audited0x70/0x71 commands are also absent. No normal
continuation command was found in this bounded complete dispatch inspection.

The USB caller at0x21a260 calls ``usbdl_handler``; on return0x21a264 branches
back to the outer listen loop at0x21a220. That loop can time out if enabled or
receive an eight-byte handshake token. BSP ``handshake_usb.c:221`` agrees:
returning from the handler ignores the synchronization garbage and resumes
listening, rather than immediately returning to main. BSP ``main.c:752``
accepts the eight-byte ``FASTBOOT`` token, acknowledges ``TOOBTSAF`` and sets
FASTBOOT mode. The stock binary contains that token and a reference at0x21ce40;
full exact-binary proof of its enclosing mode handler is not claimed here.

WRITE32 permissions and cache behavior
-------------------------------------

The actual D4 implementation validates alignment/length and calls
``sec_region_check`` at0x227910. That calls the whitelist logic at0x2278b0.
The write table at0x238e68 contains only:

* 0x10007000, length0x1000 (watchdog register block).
* 0x1001a080, length4 (USB download flag).

The bounded Unicorn replay of the original range-check code accepts four-byte
requests inside those entries and rejects0x202d40 (preloader code), a synthetic
stack address0x50002000, LK RAM0x48000000, and DA RAM0x40200000. It performs
only comparisons and no hardware/register writes. Therefore support for the
D4 opcode does not imply arbitrary RAM-write access. A live security-bypassed
or modified preloader could differ, but such differences would need separate
identity and policy evidence.

When a WRITE32 address is allowed, the store is at0x202e3c. Its loop and status
return contain no instruction-cache invalidation or synchronization. Stock
entry at0x2010e0..0x2010f4 sets SCTLR mask0x1840 and clears data-cache bit2
(mask0x4): instruction caching is enabled, data caching is disabled in
that entry sequence. This is a static startup observation, not a live SCTLR
read. Replacing a hot instruction in the command dispatcher cannot be assumed
to affect instruction fetch immediately.

Existing ARM helpers are present:0x201174 performs ICIALLU then returns;
0x201180 performs ISB then returns;0x201188 invalidates branch predictions and
disables I-cache/branch prediction;0x2011a0 disables SMP. The stock JUMP_DA
path calls these and then enters the DA with DownloadArg context, so it does
not satisfy the requested preservation route. The generic read/write command
protocol does not expose a supported arbitrary call or cache-maintenance
operation. Merely locating these functions is not a safe invocation mechanism.

Normal boot and a future hook
-----------------------------

The supplied BSP's normal ``main`` calls ``bldr_handshake`` before
``bldr_load_images``, then performs post-processing, trustzone post-init and
the normal ATF/GZ transition. A correctly admitted return could preserve this
flow better than entering a DA. However, a preloaded replacement LK would be
overwritten by the later normal LK load. A volatile hook would need an exact,
verified placement after the real LK copy/authentication completes and before
the final ATF/GZ handoff; it would also need original control-flow/register
preservation, instruction-cache coherence, and a verified bounded scratch
allocation outside preloader/firmware reservations.

This audit establishes the real loop epilogue and its caller, permission
barriers, and cache helpers. It does not establish a writable live hook site,
a coherent entry mechanism, a verified post-LK-load hook, or a successfully
resumed hardware boot. No arbitrary RAM patch, DA jump, watchdog write, reboot,
or flash operation was performed.

Evidence
--------

``preloader-continuation-evidence.json`` retains the initial epilogue-only
replay. ``preloader-continuation-with-regions-evidence.json`` adds the exact
whitelist disassembly and six pure region-check test vectors. Reproduce the
latter with a new output path using the supplied audit script's ``--preloader``
and ``--output`` arguments.
