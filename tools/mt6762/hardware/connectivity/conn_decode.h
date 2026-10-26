/* SPDX-License-Identifier: MIT
 * Pure bounded byte parsers. No IO, allocations, credentials, or ownership grants.
 * Structural success is NOT artifact authenticity or live firmware compatibility.
 */
#ifndef MT6762_CONN_DECODE_H
#define MT6762_CONN_DECODE_H
#include <stddef.h>
#include <stdint.h>
enum conn_error { CONN_OK, CONN_SIZE, CONN_FORMAT, CONN_RANGE, CONN_DUPLICATE };
enum conn_kind { CONN_WLAN = 1, CONN_WMT_PATCH, CONN_WMT_RAM, CONN_CALIBRATION };
struct conn_region { uint32_t offset, length, device_address, feature; };
struct conn_image {
 uint32_t kind, payload_bytes, region_count, chip, eco, format, flags;
 uint32_t hw_version, sw_version, target, image_type, own_version, peer_version;
 struct conn_region regions[16];
};
int conn_image_parse(const uint8_t *, size_t, unsigned, struct conn_image *);
/* Version 1 is a project observation format, NOT a shipped firmware format.
 * Header48: magic8 "MTKCONN1", version/u16, header_bytes/u16, count/u16,
 * entry_bytes/u16, total/u32, flags/u32=0, begin/end/hz u64.
 * Entry24: PA/u64, first/second u32, width/u8=4, valid/u8 (bits0,1),
 * reserved/u16=0, reserved/u32=0. LE. No implied identity or recency binding.
 */
enum conn_power { CONN_UNKNOWN, CONN_OFF, CONN_TRANSITION, CONN_ISOLATED, CONN_POWER_BITS_READY };
struct conn_state { uint32_t seen, stable, missing, power, survey_enabled; uint64_t begin, end, hz; };
/* survey_enabled must be explicit 1; default 0 only decodes, no classification.
 * Even POWER_BITS_READY is only a passive observation; clocks, rails, ADIE,
 * EMI/MPU ownership, firmware and DMA accessibility remain unproved.
 */
int conn_state_parse(const uint8_t *, size_t, unsigned survey_enabled, struct conn_state *);
size_t conn_register_count(void);
uint64_t conn_register_address(size_t);
#endif
