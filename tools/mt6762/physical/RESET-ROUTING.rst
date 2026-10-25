Pinned preloader and DA reset routing
====================================

The captured RGU reset acknowledgements do not establish recovery or XNU entry.
The observed transient USB identity0e8d:0003 must not be treated as proof of
misrouting: the user confirms this BROM enumeration can precede normal boot.
BCB consumption is a later LK decision. This audit explains specific software
paths without changing the phone or proposing an arbitrary flag modification.

Artifacts and reproducibility
-----------------------------

``audit_reset_routing.py`` reads the exact retained preloader and original
MTK_DA_V5 loader. It checks full SHA-256 identities before extracting entry22's
DA2 at file0x7538a4, length0x5118c, runtime0x40000000. The original DA2 hash is
658ff869c301fadc1a84a9409a55b5b5bdcf01524a1f904aad29a89a07ef2dec.
The complete loader/preloader hashes and bounded code ranges are retained in
``reset-routing-evidence.json``. No target bytes are distributed.

With the existing Python capstone/unicorn dependencies::

  python3 audit_reset_routing.py --preloader /path/to/preloader.bin \
    --loader /path/to/MTK_DA_V5.bin --output /private/reset-routing.json

Four original preloader safe-mode executions, four original DA dispatcher
executions and two original DA watchdog-reset executions pass. The dispatcher
uses controlled transport, connected-USB status, USB-disconnect, RTC-reset-time
and delay callbacks. Its board capability routines execute their original
instructions. The watchdog helper runs its original floating-point conversion
and MMIO sequence against plain modeled memory, stopping at SWRST. No physical
register, storage or USB operation is performed.

Observed flag is not an enabled download request
------------------------------------------------

The pre-reset USBDL_FLAG value0x444cfffc at0x1001a080 has enablebit0 clear.
In the supplied mt6765 register definitions, bit1 selects the USB-download
handler and bits15:2 encode its timeout. The timeout field is all ones, but
the download-enable bit is still zero. Do not equate magic+maximum timeout
with an enabled forced-BROM request.

The exact preloader implementation at0x223aa4 corroborates the encoding. It
uses literal USBDL_FLAG0x1001a080 and magic0x444c0000, converts nonzero timeout
from milliseconds, selects0xfffc for timeout0, and ORs bit0 only when en!=0.
It writes the MISC_LOCK key0xad98, ORs RST_CON bit0, releases the lock and writes
the resulting flag. Its exact output for en0/timeout0 is0x444cfffc; en1/timeout0
is0x444cfffd. The captured value therefore matches disabled safe mode.

The exact image has safe-mode disable calls with arguments0,0 at0x21c3f6 and
0x21c45e, and an early enable call with arguments1,5000 at0x21c4fe. These are
software-path facts, not evidence that one of those calls ran in the latest
trial. The generic BSP's optional USB-auto-detect reset flow must not be assumed
active merely from its source: its distinctive strings are absent from the
retained image, and an aligned direct-call scan found only these calls and the
emergency wrapper at0x223b00. This bounded search does not prove every possible
indirect path absent.

NORMAL and HOME_SCREEN are different DA command paths
----------------------------------------------------

The local mtkclient ``xflash_lib.py`` sends SHUTDOWN0x010007 followed by eight
little-endian words::

  hasflags, enablewdt, async_mode, bootmode, dl_bit, dont_resetrtc, leaveusb, 0

Its NORMAL/default call sends eight zeros. HOME_SCREEN (bootmode1) sets hasflags
and sends1,0,0,1,0,0,0,0. The routine hardcodes enablewdt0, dont_resetrtc0 and
leaveusb0. These names and comments alone do not establish the DA's behavior.

The pinned ``cmd_shutdown`` begins at0x400054ac. Its receive callback is supplied
an initial28-byte length for the seven consumed fields; the audit copies that
bounded prefix of the eight-word host request. Actual transport length handling
is outside this controlled replay. With connected USB modeled, the code invokes
its USB-disconnect and RTC-reset-time callbacks before testing hasflags.

* hasflags0 branches at0x40005544 to0x400055fa, then enters the loop at0x400055fc.
  It does not invoke the watchdog-reset callback on this path. The external
  USB/RTC callbacks may have effects not represented by this audit; this is not
  a claim that every physical shutdown operation is inert.
* hasflags1/bootmode1 sets bit0 in the callback flags and invokes table
  0x4004f5a0+0x18 at0x400055ee..55f8. This pointer is0x40017451, a Thumb thunk
  to0x400170a0. r0 is the low16 bits of the received enablewdt word; r1 is1.
  There is no conditional suppressing this call when enablewdt is zero.
* Both controlled HOME_SCREEN cases, enablewdt0 and enablewdt1, reach the same
  callback with first argument0 or1 respectively. The original capability
  functions at0x4003a3ec and0x4003a3f0 return zero, so this image does not take
  the alternate cold-reset/fastboot-capability branches. A bootmode2 input
  reaches the same callback with flags0x10; that alone does not prove a usable
  physical fastboot reboot.

DA reset preparation differs from LK reset preparation
-----------------------------------------------------

The original DA helper at0x400170a0, invoked with flags1 and first argument0 or1,
produces the following modeled sequence from STATUS0, MODE0x64 and the observed
USBDL_FLAG0x444cfffc:

1. Write0x95000000 to LATCH_CTL2 at0x10007048.
2. Write0x22000004 to MODE at0x10007000.
3. Clear USBDL_FLAG at0x1001a080 to zero.
4. Invoke the delay callback with argument0 for these two tested inputs.
5. Write SWRST0x1209 at0x10007014.

The original LK reset helper preserves different MODE bits, preserves the
USBDL flag, and disables PWRAP before SWRST (see ``lk-reset-review.rst``).
These are materially different software sequences. Replaying the LK sequence
from DA therefore does not reproduce every DA-reset prerequisite. Conversely,
this difference does not establish that the remaining flag caused BROM entry,
or authorize replacing it with a guessed value: the observed flag already has
its enable bit clear, and the boot ROM's interpretation and reset-retention
semantics are not available in the audited artifacts.

No phone state was changed by this investigation. The current physical outcome
still requires a later-stage observation such as a verified loader trace,
LK/serial evidence or visible payload output. An ACK, a short-lived USB identity
or the BCB's contents alone cannot establish that result.
