/* Original bounded management subset; no MMIO, allocation, transport or retries. */
#ifndef MTK_WMT_PROTOCOL_H
#define MTK_WMT_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#define CW_STP_MAX 2048u
#define CW_WMT_MAX 64u
#define CW_POLL_MAX 1000000u
enum cw_error { CW_OK=0, CW_DISABLED=-1, CW_ARGUMENT=-2, CW_STATE=-3,
 CW_HEADER=-4, CW_CHECKSUM=-5, CW_CRC=-6, CW_LENGTH=-7, CW_CHANNEL=-8,
 CW_SEQUENCE=-9, CW_ACK=-10, CW_EVENT=-11, CW_STATUS=-12,
 CW_TIMEOUT=-13, CW_CLOCK=-14, CW_BUDGET=-15 };
enum cw_mode { CW_BTIF_MANDATORY=1, CW_BTIF_FULL=2 };
enum cw_phase { CW_OFF=0, CW_NEW=1, CW_WAIT_DEFAULT=2, CW_DEFAULT_VERIFIED=3,
 CW_WAIT_SET=4, CW_SWITCH_WAIT=5, CW_FULL=6, CW_WAIT_FULL=7,
 CW_OPTIONS_VERIFIED=8, CW_FAILED=9 };
enum cw_command { CW_QUERY_DEFAULT=1, CW_SET_FULL=2, CW_QUERY_FULL=3 };
/* Caller-owned, single-threaded state. No member authorizes hardware access. */
struct cw_session {
 uint8_t packet[CW_STP_MAX+6], wmt[CW_WMT_MAX];
 uint32_t used, need, wused, wneed, polls;
 uint64_t last_us, deadline_us, switch_us;
 int error;
 uint8_t phase, mode, active, rxseq, txseq, txack, tx_acked, event_seen;
 uint8_t ack_pending, ack_value, delimiters, pda_ready;
 uint32_t packets, events, acknowledgements;
};
uint16_t cw_crc16(const uint8_t *, size_t);
void cw_init(struct cw_session *, unsigned enabled);
/* Times are monotonic microseconds; timeout 1ms..10s. No retransmission. */
int cw_poll(struct cw_session *, uint64_t now_us);
int cw_command(struct cw_session *, enum cw_command, uint64_t now_us,
 uint64_t timeout_us, uint8_t *out, size_t capacity, size_t *written);
/* Caller attestation: completed PDA patch transfer and matched firmware reset
 * response. Artifact validation alone does not qualify. No download is done here. */
int cw_attest_pda_patch_reset(struct cw_session *, uint64_t now_us);
/* Explicit caller confirmation of host framing reconfiguration; >=10ms after SET event. */
int cw_enter_full(struct cw_session *, uint64_t now_us);
/* Split/coalesced BTIF bytes. Failure is sticky; no bytes accepted afterward. */
int cw_feed(struct cw_session *, const uint8_t *, size_t, uint64_t now_us);
/* Full-mode cumulative ACK bytes; caller must transmit, and check its own result. */
int cw_take_ack(struct cw_session *, uint8_t out[4]);
#endif
