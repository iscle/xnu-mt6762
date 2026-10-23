/* Native MT6762 platform contract. No default hardware activation. */
#ifndef MT6762_PLATFORM_H
#define MT6762_PLATFORM_H
#include <sys/types.h>
#ifdef __cplusplus
extern "C" {
#endif
void mt6762_platform_init(void);
/* Read-only ADT attachment, safe before MiniFB starts. No DMA or MMIO access. */
void mt6762_platform_attach(void);
int mt6762_platform_ready(void);
int mt6762_handoff_u32(const char *, uint32_t *);
int mt6762_handoff_u64(const char *, uint64_t *);
void *mt6762_map_mmio(uint64_t physical, size_t bytes);
/* Serialized per bus. One read/write or a combined write/repeated-START/read.
 * No bytes are published on error. Do not call from an interrupt context. */
int mt6762_i2c_transfer(unsigned bus, unsigned address, const void *tx,
                       size_t tx_length, void *rx, size_t rx_length);
int mt6762_i2c_ready(unsigned bus);
int mt6762_gpio_input(unsigned pin, unsigned *level);
#ifdef __cplusplus
}
#endif
#endif
