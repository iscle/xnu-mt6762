Manufacturer reconciliation
==========================

Primary source: `Prisemi PSC5425E Rev06.5
<https://www.prisemi.com/pdf/1ldccdxp/PSC5425E.pdf>`_, pages 17–19 and 25–28.
Retrieval/hash metadata accompanies the source package; the PDF is not copied
into this repository.

The voltage encoding is intentionally discontinuous; stock's unusual CV
values agree. ADD20MV and ICE must be read rather than assumed. Charge-current
translation requires independently established board sense resistance; stock's
50-milliohm table is software evidence, not a resistor measurement.

``bsd/dev/mt6762_charger_protocol.h`` supplies nominal decoders and a
CE-disable/readback operation, with no enable operation. Unlimited input
current and reserved voltage codes return errors. Register 4 bit 7 resets
parameters; no native write targets it. Register 0's upper bits are reserved,
so the stock purported watchdog write is not reproduced. The 32-second
watchdog concerns OTG; normal charging still needs host thermal supervision.

Enabling remains blocked by actual resistor/ICE state, cell specification,
calibrated battery temperature/current, adapter budget, and a verified
independent disable fallback. Chip die thermal shutdown is not battery
thermistor protection. See NATIVE.rst for ownership/failure semantics.
