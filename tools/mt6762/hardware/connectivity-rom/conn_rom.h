/* SPDX-License-Identifier: MIT
 * Exact shipped MT6765 RAM profile; original bounded reset-held EMI consumer.
 * No MMIO, mapping, allocation, PMIC, reset release, PDA, DMA or radio control.
 */
#ifndef MT6762_CONN_ROM_H
#define MT6762_CONN_ROM_H
#include <stddef.h>
#include <stdint.h>
#define CR_IMAGES 3U
#define CR_CHUNK 1024U
#define CR_CONSYS_BYTES UINT64_C(0x400000)
#define CR_COUNTER_HZ 13000000U
enum cr_result { CR_OK=0,CR_DISABLED=1,CR_ARGUMENT=-1,CR_RANGE=-2,
    CR_OVERLAP=-3,CR_HEADER=-4,CR_SOURCE_HASH=-5,CR_ADMISSION=-6,
    CR_STATE=-7,CR_TIMEOUT=-8,CR_LIMIT=-9,CR_IO=-10,
    CR_SHORT=-11,CR_READBACK=-12,CR_SOURCE_CHANGED=-13 };
enum cr_phase { CR_NONE,CR_VALIDATE,CR_HASH,CR_COPY,CR_PUBLISH,
    CR_INVALIDATE,CR_READBACK_PHASE,CR_BUILD_TIME,CR_FINISH };
enum cr_cache_action { CR_CACHE_PUBLISH,CR_CACHE_PREPARE_READ };
struct cr_source { const uint8_t *bytes; size_t length; uint64_t physical_address; };
struct cr_request {
    unsigned enabled; /* exactly 1 executes, 0 calls no callbacks */
    uint32_t counter_hz,timeout_us,operation_limit; /* 13MHz; 1..5s; 1..20000 */
    uint64_t lease_epoch,consys_base,consys_bytes;
    struct cr_source image[CR_IMAGES]; /* immutable order BT, Wi-Fi, MCU */
};
/* Snapshot supplied by a real adapter under exclusive ownership, not an
 * authorization token. MMIO values must be current ordinary reads; the owner
 * must also check actual rail/clock/MPU/mapping/source-immutability prerequisites.
 * No historical capture or constant-return adapter can establish these facts.
 */
struct cr_live {
    uint64_t lease_epoch,owned_base,owned_bytes;
    uint32_t rgu_reset,spm_control,power_status,power_status2;
    uint32_t ip_id,hw_version,fw_version,emi_remap;
};
struct cr_io {
    void *context;
    uint64_t (*ticks)(void *);
    int (*observe)(void *,enum cr_phase,struct cr_live *);
    /* Each callback is synchronous, nonblocking and bounded. No retries here.
     * A nonzero result may still mean some/all bytes reached destination.
     * completed must equal n on success; never round up an unaligned tail.
     */
    int (*write)(void *,uint64_t,const uint8_t *,size_t,size_t *completed);
    int (*read)(void *,uint64_t,uint8_t *,size_t,size_t *completed);
    /* PUBLISH: make completed stores visible to CONN, plus required barrier.
     * PREPARE_READ: prevent cached/stale alias from faking physical readback.
     * Adapter owns attributes, line rounding and all affected cache lines.
     */
    int (*synchronize)(void *,uint64_t,size_t,enum cr_cache_action);
};
struct cr_report {
    int result,callback_error;
    enum cr_phase phase;
    uint32_t image,validated_images,completed_images,operations,observations;
    uint32_t write_attempts,writes,reads,synchronizations;
    uint64_t last_address,source_bytes_hashed,bytes_written,bytes_verified;
    uint64_t began_ticks,ended_ticks;
    size_t last_requested,last_completed;
    struct cr_live first,last; /* only successfully returned observations */
};
/* Own outside small kernel stack. The function snapshots request/io here.
 * No aliases among workspace/report/request/io/image buffers are permitted.
 */
struct cr_workspace {
    uint8_t source[CR_CHUNK],readback[CR_CHUNK],header[CR_IMAGES][48];
    struct cr_request request;
    struct cr_io io;
};
/* Immutable profile metadata is public; original firmware bytes are not. */
struct cr_profile {
    const char *filename;
    uint32_t type,file_bytes,offset,buildtime_offset;
    uint8_t file_sha256[32],body_sha256[32];
};
const struct cr_profile *cr_profile_at(size_t);
/* Success only means these exact bytes were staged and read back under the
 * adapter's maintained admission. Caller retains reset/lease on every exit.
 * No rollback, retries, automatic poweroff or implied later-stage grant.
 * On any invalid argument/layout, returns without touching report.
 */
int cr_stage(const struct cr_request *,const struct cr_io *,
             struct cr_workspace *,struct cr_report *);
#endif
