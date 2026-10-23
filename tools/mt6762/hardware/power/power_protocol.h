/* Local research backend. See README.rst for evidence and unimplemented policy. */
#ifndef MT6762_POWER_PROTOCOL_H
#define MT6762_POWER_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
enum { POWER_OK=0, POWER_IO=-1, POWER_INVALID=-2, POWER_TIMEOUT=-3,
       POWER_NOT_READY=-4, POWER_ID_MISMATCH=-5 };
struct power_i2c_msg { uint8_t address, read; uint16_t length; uint8_t *data; };
/* Return exactly nmsgs on success; preserve repeated START between messages.
 * Caller serializes the whole public operation, including read/modify/write. */
struct power_i2c { void *ctx; int (*transfer)(void *, struct power_i2c_msg *, size_t); };
struct psc5425e_snapshot { uint8_t identity, status, control, voltage, current;
                         uint8_t status_code, charge_disabled, done; };
int psc5425e_read(const struct power_i2c *, uint8_t reg, uint8_t *out);
int psc5425e_snapshot(const struct power_i2c *, struct psc5425e_snapshot *out);
/* Only disable is exposed. No guessed battery limits, enable or OTG writes. */
int psc5425e_disable_charge(const struct power_i2c *);
struct power_mmio { void *ctx; int (*read32)(void *, uint32_t, uint32_t *);
                    int (*write32)(void *, uint32_t, uint32_t); };
/* Offsets relative to 0x1000d000. Requires bootloader-initialized wrapper,
 * exclusive WACS2 ownership and ordered MMIO. max_polls is a hard bound. */
int mt6765_pwrap_read16(const struct power_mmio *, uint16_t address,
                       uint16_t *out, unsigned max_polls);
/* PMIC TOPSTATUS 0x24 fields from BSP register definitions, active low keys. */
struct mt6357_keys { uint8_t power, home, charger_present; };
struct mt6357_keys mt6357_decode_topstatus(uint16_t raw);
/* Matrix index, not physical button identity. Reads KP_MEM1..5 as 16-bit. */
int mt6765_key_pressed(const uint16_t state[5], unsigned index);
#endif
