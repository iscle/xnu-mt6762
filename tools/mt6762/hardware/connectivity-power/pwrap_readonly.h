/* SPDX-License-Identifier: MIT
 * Optional loader adapter for the existing native WACS read protocol.
 * Serialization and live inherited-profile admission are supplied by owner.
 * No initialization, recovery, PMIC writes or ownership grant occurs here.
 */
#ifndef MT6762_CONNECTIVITY_PWRAP_READONLY_H
#define MT6762_CONNECTIVITY_PWRAP_READONLY_H
#include "../../physical/connectivity_probe.h"
/* The existing shared protocol also defines unrelated static ADC/key helpers.
 * Keep the diagnostic exception local to that unchanged include, so actual
 * freestanding consumers retain -Wall -Wextra -Werror for all new code. */
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#include "../../../../bsd/dev/mt6762_power_protocol.h"
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif
enum { MT6762_CONNECTIVITY_WACS_ARGUMENT=-1001,
       MT6762_CONNECTIVITY_WACS_FAULTED=-1002 };
struct mt6762_connectivity_pwrap {
    void *context;
    const struct mt6762_wacs_io *io;
    int (*acquire)(void *);
    void (*release)(void *);
    int (*admit)(void *); /* 0 only after real live LK22 wrapper admission. */
    int fault;
};
/* Suitable as read_pmic16 callback. A context aggregator may forward here.
 * The existing protocol necessarily writes READ commands to WACS2_CMD and
 * acknowledges only this completed read through VLDCLR. It never sets the
 * PMIC-write bit. A transport error poisons this adapter until owner recovery;
 * subsequent calls neither retry nor clear someone else's pending response.
 */
static inline int mt6762_connectivity_pwrap_read(void *context,uint16_t address,
    uint16_t *value)
{
    struct mt6762_connectivity_pwrap *p=context;
    if(!p || !p->io || !p->io->read || !p->io->write || !p->io->delay_us ||
       !p->acquire || !p->release || !p->admit || !value ||
       !mt6762_connectivity_pmic_allowed(address))return MT6762_CONNECTIVITY_WACS_ARGUMENT;
    int error=p->acquire(p->context);
    if(error)return error;
    if(p->fault) {p->release(p->context);return MT6762_CONNECTIVITY_WACS_FAULTED;}
    error=p->admit(p->context);
    if(!error)error=mt6762_wacs_transfer_profile(p->io,MT6762_WACS_LK22,0,address,value);
    if(error)p->fault=1;
    p->release(p->context);
    return error;
}
#endif
