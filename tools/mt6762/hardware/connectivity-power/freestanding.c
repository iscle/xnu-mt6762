/* SPDX-License-Identifier: MIT -- compile-only real loader consumer API. */
#include "pwrap_readonly.h"
int connectivity_loader_consumer(const struct mt6762_connectivity_io *io,
    volatile struct mt6762_connectivity_record *record,const uint8_t identity[32],int enabled)
{
    return mt6762_connectivity_capture(io,record,identity,enabled);
}
int connectivity_loader_pmic_consumer(struct mt6762_connectivity_pwrap *p,
    uint16_t address,uint16_t *value)
{
    return mt6762_connectivity_pwrap_read(p,address,value);
}
