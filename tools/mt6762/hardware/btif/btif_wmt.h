/* One bounded cold-ROM option query; no firmware download or radio enable. */
#ifndef MT6762_BTIF_WMT_H
#define MT6762_BTIF_WMT_H
#include "btif_pio.h"
#include "../connectivity/wmt_protocol.h"
enum btif_wmt_phase { BTIF_WMT_NEW=0, BTIF_WMT_QUERY=1,
                     BTIF_WMT_DEFAULT_OPTIONS=2, BTIF_WMT_FAILED=3 };
struct btif_wmt_query {
    struct btif_pio transport;
    struct cw_session protocol;
    uint8_t tx[CW_WMT_MAX+6],rx[32];
    enum btif_wmt_phase phase;
    int transport_error,protocol_error;
};
/* Zero-initialize query. An ownership grant is supplied by the real hardware
 * adapter, not derived from file validation or a successful prior simulation. */
int btif_wmt_start(struct btif_wmt_query *,const struct btif_pio_io *,
                   const struct btif_pio_grant *,uint64_t now_us,uint64_t timeout_us);
int btif_wmt_step(struct btif_wmt_query *,uint64_t now_us);
#endif
