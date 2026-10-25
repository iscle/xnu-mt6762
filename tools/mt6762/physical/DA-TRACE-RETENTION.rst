RAM trace survival through download-agent reconnection
======================================================

The image5 trace address0x40084000 is part of the temporary Linux Image's own
reserved storage while that payload runs. This does not reserve it from a later
preloader or download agent. Absence of its marker after reconnection cannot
establish that XNU or the diagnostic loader did not execute.

Exact selected download agent
----------------------------

``audit_da_trace.py`` pins MTK_DA_V5.bin SHA256
``aef234190ccb8145d2e3b8459741e9adb70f2caa8481aa216c1b25152afaca1f``
and independently decodes the zero-based entry22 for hardware0x6765 using the
0xdc-byte entry/20-byte region format in mtkclient's DA/daconfig.py.

DA1 loads at0x00200000 with length0x39f98, including0x100 signature bytes.
DA2's region begins at loader offset0x7538a4, loads at0x40000000 and has
length0x5118c, including0x100 signature bytes. DA2's complete region digest is
``658ff869c301fadc1a84a9409a55b5b5bdcf01524a1f904aad29a89a07ef2dec``.
The earlier0x40200000 value is not this DA2 load address.

The exact ARM entry clears BSS [0x40051090,0x4005e2a0). Its initial banked
stack top is0x400530c0. These bounded startup writes do not reach the trace.
However, kmain calls allocator initialization at0x4000add4. That routine sets
heap base0x4005e2a0; its size getter0x4000a338 subtracts this base from the
constant0x68000000. The heap therefore owns [0x4005e2a0,0x68000000), which
contains0x40084000. Startup requests1MiB idle/bootstrap thread stacks through
this allocator, as well as an8KiB monitor stack. Thread setup clears only the
top0xac context bytes, so this audit does not claim an immediate whole-stack
zero or a specific observed overwrite. Runtime stack/allocation use suffices
to make retention unproven. Later buffers, DA1, patches/extensions and preloader
DRAM setup have not been exhaustively audited.

Capturing before DA upload is also constrained
---------------------------------------------

The exact retained preloader's READ32 command0xd1 starts at0x202f9e. At0x2030e2
it checks ``sec_region_check(address, count*4, OP_READ=1)`` before the data load.
Its read whitelist is exactly these three ranges:

* 0x10007000 through0x10007fff;
* 0x1001a080 through0x1001a083;
* 0x11c50000 through0x11c50fff.

``audit_preloader_read_regions.py`` executes the original pure range checker
with synthetic arguments. Nine cases pass:0x40084000 with4 or256 bytes and
0x40200000 are rejected with0x105006; complete allowed ranges pass; crossing
range boundaries fails; address overflow returns0x105002. The test does not
dereference those addresses or issue USB commands. Thus ordinary stock
preloader READ32 cannot capture this DRAM marker before DA upload. BROM READ32
is a different implementation and is not established as an alternative here;
entering BROM also does not prove DRAM preservation.

No unclaimed replacement address is proposed. Moving the marker beyond the
known heap would still require current DRAM/reservation validation and a proof
of preloader, DA and DMA ownership there. A fully validated marker after DA
reconnection can be positive evidence; missing or damaged data is inconclusive.
The readout must check its version, expected payload identity and consistency
rather than treating an arbitrary matching word as proof.

Reproduction (offline, existing capstone/unicorn modules)::

  python3 audit_da_trace.py --loader /path/to/MTK_DA_V5.bin \
    --output /private/da-trace-evidence.json
  python3 audit_preloader_read_regions.py --preloader /path/to/preloader.bin \
    --output /private/preloader-read-regions-evidence.json

Both tools reject other artifact digests. Outputs contain bounded instructions,
hashes, range metadata and synthetic test results, not proprietary binary blobs
or private phone logs. Neither tool implements a device transport or write.
