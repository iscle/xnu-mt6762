/* SPDX-License-Identifier: MIT */
#ifndef MT6762_CONN_ROM_SHA256_H
#define MT6762_CONN_ROM_SHA256_H
#include <stddef.h>
#include <stdint.h>
struct cr_sha256 { uint32_t state[8]; uint64_t bytes; uint8_t block[64]; size_t used; };
void cr_sha256_init(struct cr_sha256 *);
void cr_sha256_update(struct cr_sha256 *, const uint8_t *, size_t);
void cr_sha256_final(struct cr_sha256 *, uint8_t digest[32]);
#endif
