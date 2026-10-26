/* Original bounded MT6765 BTIF PIO transport. See README.rst for provenance.
 * No power, clock, DMA, interrupt-controller or allocation operations here. */
#ifndef MT6762_BTIF_PIO_H
#define MT6762_BTIF_PIO_H
#include <stddef.h>
#include <stdint.h>

enum btif_pio_error {
    BTIF_OK=0, BTIF_DISABLED=-1, BTIF_ARGUMENT=-2, BTIF_OWNERSHIP=-3,
    BTIF_BUSY=-4, BTIF_CONFIG=-5, BTIF_STATE=-6, BTIF_TIMEOUT=-7,
    BTIF_CLOCK=-8, BTIF_BUDGET=-9
};
/* ready must recheck accessibility/clock/ownership using always-on registers,
 * before accessing BTIF. It must not probe the CONSYS aperture to decide this.
 * Every register callback performs its required device-memory barriers.
 * An admitted caller serializes this entire transport, including RX/ACK TX. */
struct btif_pio_io {
    void *context;
    int (*ready)(void *);
    uint32_t (*read32)(void *, unsigned);
    void (*write32)(void *, unsigned, uint32_t);
    uint8_t (*read8)(void *, unsigned);
    void (*write8)(void *, unsigned, uint8_t);
};
struct btif_pio_grant {
    unsigned enabled, exclusive, irq_masked, apdma_idle;
};
struct btif_pio {
    struct btif_pio_io io;
    const uint8_t *tx;
    size_t tx_length, tx_written;
    uint64_t last_us, deadline_us;
    uint32_t polls, rx_total;
    int error;
    unsigned initialized, active, tx_complete;
};
/* Zero-initialize state before first use. Refuses live DMA, queued RX or TX.
 * No FIFO flush: inherited bytes are never discarded. RX IRQ generation is
 * enabled for IIR polling, but the caller must keep its GIC source masked. */
int btif_pio_init(struct btif_pio *, const struct btif_pio_io *,
                  const struct btif_pio_grant *);
/* Buffer remains owned by caller until finish/failure. No retries, no copying.
 * Receive-only windows (tx=NULL,length=0) are supported. Timeout1ms..10s. */
int btif_pio_begin(struct btif_pio *, const uint8_t *, size_t,
                   uint64_t now_us, uint64_t timeout_us);
/* At most32 RX and16 TX bytes per call. All TX writes/RX reads are8-bit.
 * received is zero on error; discard the entire protocol exchange on failure.
 * Caller calls its protocol parser, then polls again until a matched reply.
 * No wait/delay in this core; monotonic time and a poll budget bound progress. */
int btif_pio_step(struct btif_pio *, uint8_t *, size_t capacity,
                  size_t *received, uint64_t now_us);
/* Success means local TX FIFO drained before deadline, NOT a firmware ACK. */
int btif_pio_finish(struct btif_pio *, uint64_t now_us);
#endif
