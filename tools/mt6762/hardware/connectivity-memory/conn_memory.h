#ifndef MT6762_CONN_MEMORY_H
#define MT6762_CONN_MEMORY_H
#include <stdint.h>
#include <stddef.h>
#include "../../physical/fdt_handoff.h"
#define CM_MBLOCK_BYTES 22552U
#define CM_MAX_BLOCKS 128U
#define CM_MAX_CONSTRAINTS 16U
#define CM_MAX_EXTRA 64U
#define CM_ALIGNMENT UINT64_C(0x1000000)
#define CM_CONSYS_BYTES UINT64_C(0x400000)
#define CM_WIFI_BYTES UINT64_C(0x300000)
/* No error grants memory, mappings, DMA, power or peripheral ownership. */
enum cm_error { CM_OK=0, CM_DISABLED=-1, CM_ARGUMENT=-2, CM_FDT=-3,
    CM_FORMAT=-4, CM_COUNT=-5, CM_RANGE=-6, CM_OVERLAP=-7,
    CM_COVERAGE=-8, CM_OWNER=-9, CM_NO_SPACE=-10 };
struct cm_table {
    struct mtk_fdt_range free[CM_MAX_BLOCKS], reserved[CM_MAX_BLOCKS];
    uint32_t free_count, reserved_count;
    uint64_t free_bytes, reserved_bytes, bank_bytes;
};
struct cm_request {
    uint32_t enabled, reserved_zero;
    /* Caller-supplied fresh boot identifier, NOT authentication/attestation. */
    uint64_t boot_nonce, fdt_pa;
    /* Required complete owned ranges. They may overlap each other. */
    struct mtk_fdt_range source_image, kernel_managed, loader_live;
    const struct mtk_fdt_range *additional;
    size_t additional_count;
};
struct cm_ledger {
    uint32_t version, count;
    uint64_t boot_nonce, fdt_pa, fdt_bytes;
    /* Entries in immutable order: CONSYS, Wi-Fi. Proposal only, not committed. */
    struct mtk_fdt_range proposed[2];
    uint64_t bank_bytes, free_bytes, lk_reserved_bytes;
    uint32_t lk_free_count, lk_reserved_count;
};
/* Caller owns this workspace. No allocation and no large automatic arrays.
 * Workspace, output, request, FDT and input ranges must not alias. */
struct cm_workspace {
    struct mtk_fdt_info info;
    struct cm_table table;
    struct mtk_fdt_range allowed[2][CM_MAX_CONSTRAINTS], other_dynamic[64];
    uint32_t allowed_count[2], other_count;
};
/* Exact LE LK mblock v2 ABI; banks come from validated live FDT. Empty free
 * slots are permitted; nonempty ranges must partition the supplied banks. */
int cm_parse_mblock(const void *bytes, size_t size,
    const struct mtk_fdt_range *banks, size_t bank_count, struct cm_table *out);
/* Revalidate the executing boot's immutable FDT each call. Capture files are
 * suitable ONLY for offline tests. A successful proposal has no side effects;
 * caller must atomically commit the ledger before any mapping/consumer use. */
int cm_plan(const void *fdt, size_t accessible, const struct cm_request *request,
    struct cm_workspace *workspace, struct cm_ledger *out);
#endif
