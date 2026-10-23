#include "power_protocol.h"
#define PSC_ADDRESS 0x6a
int psc5425e_read(const struct power_i2c *bus, uint8_t reg, uint8_t *out)
{
    uint8_t value=0;
    struct power_i2c_msg msg[2]={{PSC_ADDRESS,0,1,&reg},{PSC_ADDRESS,1,1,&value}};
    if (!bus || !bus->transfer || !out || reg>6) return POWER_INVALID;
    if (bus->transfer(bus->ctx,msg,2)!=2) return POWER_IO;
    *out=value;
    return POWER_OK;
}
int psc5425e_snapshot(const struct power_i2c *bus, struct psc5425e_snapshot *out)
{
    struct psc5425e_snapshot s={0};
    int e;
    if (!out) return POWER_INVALID;
    if ((e=psc5425e_read(bus,3,&s.identity))) return e;
    if (s.identity!=0xf0) return POWER_ID_MISMATCH;
    if ((e=psc5425e_read(bus,0,&s.status)) ||
        (e=psc5425e_read(bus,1,&s.control)) ||
        (e=psc5425e_read(bus,2,&s.voltage)) ||
        (e=psc5425e_read(bus,4,&s.current))) return e;
    s.status_code=(s.status>>4)&3;
    s.done=s.status_code==2;
    s.charge_disabled=(s.control>>2)&1;
    *out=s;
    return POWER_OK;
}
int psc5425e_disable_charge(const struct power_i2c *bus)
{
    uint8_t id,reg,check,bytes[2];
    struct power_i2c_msg msg={PSC_ADDRESS,0,2,bytes};
    int e;
    if ((e=psc5425e_read(bus,3,&id))) return e;
    if (id!=0xf0) return POWER_ID_MISMATCH;
    if ((e=psc5425e_read(bus,1,&reg))) return e;
    if (!(reg&4)) {
        bytes[0]=1; bytes[1]=reg|4;
        if (bus->transfer(bus->ctx,&msg,1)!=1) return POWER_IO;
    }
    if ((e=psc5425e_read(bus,1,&check))) return e;
    return (check&4) ? POWER_OK : POWER_IO;
}
static int pwrap_wait(const struct power_mmio *m, unsigned state, unsigned polls, uint32_t *v)
{
    while (polls--) {
        if (m->read32(m->ctx,0xc24,v)) return POWER_IO;
        if (!(*v&(1u<<21))) return POWER_NOT_READY;
        if (((*v>>16)&7)==state) return POWER_OK;
    }
    return POWER_TIMEOUT;
}
int mt6765_pwrap_read16(const struct power_mmio *m, uint16_t address,
                       uint16_t *out, unsigned max_polls)
{
    uint32_t v;
    int e;
    if (!m || !m->read32 || !m->write32 || !out || (address&1) || !max_polls)
        return POWER_INVALID;
    if ((e=pwrap_wait(m,0,max_polls,&v))) return e;
    if (m->write32(m->ctx,0xc20,((uint32_t)address>>1)<<16)) return POWER_IO;
    if ((e=pwrap_wait(m,6,max_polls,&v))) return e;
    if (m->write32(m->ctx,0xc28,1)) return POWER_IO;
    *out=(uint16_t)v;
    return POWER_OK;
}
struct mt6357_keys mt6357_decode_topstatus(uint16_t raw)
{
    struct mt6357_keys k={!(raw&2),!(raw&8),!!(raw&4)};
    return k;
}
int mt6765_key_pressed(const uint16_t state[5], unsigned index)
{
    if (!state || index>=72) return POWER_INVALID;
    return !(state[index/16]&(1u<<(index%16)));
}
