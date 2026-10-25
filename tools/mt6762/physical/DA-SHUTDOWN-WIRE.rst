Exact DA shutdown framing and misleading acknowledgement
=======================================================

The retained DA requires a shutdown parameter packet no larger than 28 bytes.
The local mtkclient implementation sends 32 bytes. The exact receiver rejects
that packet before copying its body, but the shutdown handler ignores the
error and still sends a zero status. A successful host status read therefore
does not establish that HOME_SCREEN fields reached the handler.

This resolves the explicit receive-callback gap in ``RESET-ROUTING.rst``.
That earlier replay supplied the 28-byte prefix through a modeled callback;
it correctly tested field dispatch, but did not test acceptance of the actual
32-byte wire packet. The new audit executes the real framed receive and send
routines and preserves this distinction. No phone command was issued here.

Pinned original and actually uploaded DA
---------------------------------------

The original DA2 SHA-256 is
658ff869c301fadc1a84a9409a55b5b5bdcf01524a1f904aad29a89a07ef2dec.
The actual patched/reserved DA2 SHA-256, verified by the parent's upload path,
is 04a293ab057fed8278e12cbde385f2ad732aebcd9d0878fe16691212c8cdca84.
The latter was reproduced offline using only ``capture_v2.preflight()``; no
connect, upload, reset or readback routine was invoked. The existing security
patcher's intermediate hash is
c10e62b2d0b2c255a7030a568676a554659276c4b63a824fe42e5cac028c769e.

``audit_da_shutdown_wire.py`` checks the loader and both DA identities, then
requires byte equality across the shutdown handler, command dispatch, framed
receiver/sender, timing wrappers and original callback-table ranges. The public
``da-shutdown-wire-evidence.json`` records their hashes and ten passing cases,
without including binary blobs. Reproduce with existing capstone/unicorn::

  python3 audit_da_shutdown_wire.py --loader /path/to/MTK_DA_V5.bin \
    --patched-da2 /private/verified-final-da2.bin --output /private/wire.json

Exact callback chain and bound
------------------------------

The dispatcher's table is 0x4004f4e0. Its receive pointer 0x4000a7fd is the Thumb
wrapper at 0x4000a7fc, which calls framed receiver 0x40006e3c. Shutdown sets a
capacity word to 0x1c at 0x400054b6..54b8, passes its address and a stack buffer
at 0x400054e6..54ea, and invokes that receive pointer.

The real framed receiver:

1. Requests a 12-byte header and verifies magic 0xfeeeeeef.
2. Loads incoming payload length from header+8.
3. Compares caller capacity with incoming length at 0x40006e7a..6e82.
4. If capacity is smaller, returns 0xc0010006 through 0x40006eae without requesting
   or copying the payload. It leaves both caller length and destination intact.
5. Otherwise stores the accepted length and requests exactly that many bytes
   into the destination at 0x40006e90..6e98.

This is a maximum-capacity check, not truncation to 28 bytes. The current 32-byte
request is rejected, and no stack overwrite occurs through this path. The
controlled raw-USB model retains its 32 body bytes unread. Physical USB FIFO or
DMA prefetching is outside this model; the established fact is that the framed
receiver never requests or copies those bytes into the shutdown fields.

Why the ACK is insufficient
---------------------------

There are two relevant zero statuses. The command dispatcher sends a zero
before invoking the command handler at 0x40006d16..6d22. Later, shutdown returns
from receive at 0x400054ec without checking r0, then transmits the four-byte
status initialized to zero at 0x400054b4. Its status send is 0x400054f4. Flags are
only inspected afterward at 0x40005540. Therefore the parameter status can be
zero even when receive returned0xc0010006.

The untouched parameter buffer is uninitialized stack storage. The audit tests
zero and 0xa5 initial fills, rather than inventing a single live value. Both
32-byte cases send a zero ACK and enter the shutdown loop; the zero-fill case
also invokes modeled USB-disconnect and RTC-reset-time callbacks, while 0xa5
skips them. The real phone's previous stack contents are unknown. This explains
why an ACK is not acceptance evidence; it does not prove which exact subsequent
path the physical trial took. Transient BROM enumeration or a black screen
alone does not resolve that remaining observation gap.

Exact bounded HOME_SCREEN packet
--------------------------------

The seven consumed little-endian words, in order, are::

  hasflags, enablewdt, async_mode, bootmode, dl_bit, dont_resetrtc, leaveusb
  1,        0,         0,          1,        0,      0,             0

For this pinned DA the exact field packet is 28 bytes; there is no eighth spare
word in this handler's capacity. The XFlash header is magic 0xfeeeeeef, protocol
type 1, length 28. Both original and patched DA tests accept the exact packet,
copy all seven fields, send their zero status and reach the watchdog callback
with arguments 0,1. A control packet with enablewdt 1 also reaches that callback,
as established by the prior field-dispatch audit.

A private future-session candidate was prepared for parent review. Its default
CLI only prints a plan. Its effectful function is never called by the module;
it requires an already active verified DA, a selected completed capture cwd,
matching upload linkage, live heap/reservation readbacks and exact live shutdown
and receiver code before sending one 28-byte request. It neither connects nor
uploads a DA, changes partitions or invents reset-register writes. It rejects
repeated attempts and records ACK as an exchange result, never as boot success.
It was tested solely against fake host objects and local bytes. No execution
on a phone is implied or authorized by this document itself.
