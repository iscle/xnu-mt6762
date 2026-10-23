/* Experimental MT6765-family transaction engine; see README.rst. */
#ifndef MTK_I2C_V2_H
#define MTK_I2C_V2_H
#include <stddef.h>
#include <stdint.h>
enum { MTK_I2C_INVALID=-1, MTK_I2C_NOT_READY=-2, MTK_I2C_BUSY=-3,
       MTK_I2C_IO=-4, MTK_I2C_TIMEOUT=-5 };
struct mtk_i2c_msg { uint8_t address, read; uint16_t length; uint8_t *data; };
struct mtk_i2c_v2 {
    void *context;
    uint16_t (*read16)(void *, unsigned offset);
    void (*write16)(void *, unsigned offset, uint16_t value);
    uint32_t (*dma_read32)(void *, unsigned offset);
    void (*dma_write32)(void *, unsigned offset, uint32_t value);
    void (*barrier)(void *);
    void (*delay_us)(void *, unsigned);
    /* Dedicated, coherent, physically contiguous buffer below 8 GiB.
     * Keep pinned even after failure until hardware DMA is proven stopped. */
    uint8_t *dma_buffer;
    uint64_t dma_address;
    size_t dma_capacity;
    unsigned timeout_us;
    unsigned bus_hz; /* Verified inherited standard/fast mode, at most 400 kHz. */
    /* Set only after exclusive ownership, clocks, pinmux, rails, timing and
     * initial idle state have been established. Never inferred by this core. */
    unsigned initialized;
    unsigned faulted;
};
/* Caller serializes all calls. One write/read or same-address write+read.
 * Success is number of messages. Error never publishes partially read data.
 * This does not initialize hardware or recover a failed transaction. */
int mtk_i2c_v2_transfer(struct mtk_i2c_v2 *, struct mtk_i2c_msg *, size_t);
#endif
