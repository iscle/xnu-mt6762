#include "mtk_i2c_v2.h"

/* Controller accesses are 16 bits. APDMA accesses are 32 bits. */
enum { DATA=0, ADDR=4, MASK=8, STATUS=12, CONTROL=16, LENGTH=20,
       TRANSACTIONS=24, START=36, FIFO_CLEAR=56, MCU_INTR=64, AUX_LENGTH=68 };
enum { DMA_FLAG=0, DMA_ENABLE=8, DMA_CON=24, DMA_TX=28, DMA_RX=32,
       DMA_TX_LEN=36, DMA_RX_LEN=40, DMA_TX_HIGH=84, DMA_RX_HIGH=88 };

int mtk_i2c_v2_transfer(struct mtk_i2c_v2 *b, struct mtk_i2c_msg *m, size_t n)
{
    size_t tx=0, rx=0, i;
    unsigned dma, elapsed;
    uint16_t control=0x28, status=0;
    uint8_t scratch[8], *out=0;
    if (!b || !m || (n!=1 && n!=2) || !b->read16 || !b->write16 ||
        !b->dma_read32 || !b->dma_write32 ||
        !b->barrier || !b->delay_us || !b->timeout_us || b->timeout_us>1000000 ||
        !b->bus_hz || b->bus_hz>400000)
        return MTK_I2C_INVALID;
    for (i=0; i<n; i++)
        if (m[i].address<8 || m[i].address>0x77 || m[i].read>1 ||
            !m[i].data || !m[i].length || m[i].length>4096)
            return MTK_I2C_INVALID;
    if (n==2 && (m[0].read || !m[1].read || m[0].address!=m[1].address))
        return MTK_I2C_INVALID;
    if (m[0].read) { rx=m[0].length; out=m[0].data; }
    else tx=m[0].length;
    if (n==2) { rx=m[1].length; out=m[1].data; }
    dma=tx>8 || rx>8;
    if (dma && (!b->dma_read32 || !b->dma_write32 || !b->dma_buffer ||
        b->dma_capacity<tx || b->dma_capacity<rx || b->dma_address>=(1ULL<<33) ||
        b->dma_capacity>((1ULL<<33)-b->dma_address)))
        return MTK_I2C_INVALID;
    if (!b->initialized || b->faulted) return MTK_I2C_NOT_READY;
    if ((b->read16(b->context, START)&1) || b->dma_read32(b->context, DMA_ENABLE))
        return MTK_I2C_BUSY;
    if (n==2) control|=0x12; /* direction change + repeated START */
    if (dma) control|=0x304; /* DMA, DMA ACK, asynchronous mode */
    b->write16(b->context, MASK, 0);
    b->write16(b->context, STATUS, 0x1ff);
    b->write16(b->context, FIFO_CLEAR, 1);
    /* Match BSP event visibility. Caller keeps this source masked in GIC. */
    b->write16(b->context, MASK, 0x12f);
    b->write16(b->context, CONTROL, control);
    b->write16(b->context, ADDR, (uint16_t)((m[0].address<<1)|m[0].read));
    b->write16(b->context, LENGTH, m[0].length);
    b->write16(b->context, AUX_LENGTH, n==2 ? m[1].length : 0);
    b->write16(b->context, TRANSACTIONS, (uint16_t)n);
    if (dma) {
        for (i=0;i<tx;i++) b->dma_buffer[i]=m[0].data[i];
        b->dma_write32(b->context, DMA_FLAG, 0);
        b->dma_write32(b->context, DMA_CON, tx ? 0 : 1);
        /* Clear unused lengths/addresses too, so prior direction cannot leak. */
        b->dma_write32(b->context, DMA_TX, tx ? (uint32_t)b->dma_address : 0);
        b->dma_write32(b->context, DMA_TX_HIGH, tx ? (uint32_t)(b->dma_address>>32) : 0);
        b->dma_write32(b->context, DMA_RX, rx ? (uint32_t)b->dma_address : 0);
        b->dma_write32(b->context, DMA_RX_HIGH, rx ? (uint32_t)(b->dma_address>>32) : 0);
        b->dma_write32(b->context, DMA_TX_LEN, (uint32_t)tx);
        b->dma_write32(b->context, DMA_RX_LEN, (uint32_t)rx);
        b->barrier(b->context);
        b->dma_write32(b->context, DMA_ENABLE, 1);
    } else for (i=0;i<tx;i++) b->write16(b->context, DATA, m[0].data[i]);
    b->write16(b->context, MCU_INTR, 1);
    b->barrier(b->context);
    b->write16(b->context, START, 1);
    for (elapsed=0;elapsed<b->timeout_us;elapsed++) {
        status=b->read16(b->context, STATUS);
        /* RS_MULTI is informational; every error wins over completion. */
        if (status&0x1ee) break;
        if ((status&1) && !(b->read16(b->context, START)&1) &&
            (!dma || !b->dma_read32(b->context, DMA_ENABLE))) break;
        b->delay_us(b->context, 1);
    }
    if ((status&0x1ee) || elapsed==b->timeout_us) {
        /* Do not reset a live bus or reuse DMA storage on an uncertain stop. */
        b->write16(b->context, MASK, 0);
        b->faulted=1;
        return (status&0x1ee) ? MTK_I2C_IO : MTK_I2C_TIMEOUT;
    }
    b->barrier(b->context);
    if (dma) for (i=0;i<rx;i++) out[i]=b->dma_buffer[i];
    else {
        for (i=0;i<rx;i++) scratch[i]=(uint8_t)b->read16(b->context, DATA);
        for (i=0;i<rx;i++) out[i]=scratch[i];
    }
    b->write16(b->context, MASK, 0);
    b->write16(b->context, STATUS, status&0x1ff);
    return (int)n;
}
