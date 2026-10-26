#ifndef MTK_FDT_HANDOFF_H
#define MTK_FDT_HANDOFF_H
#include <stddef.h>
#include <stdint.h>
#define MTK_FDT_MAX_SIZE (2U * 1024U * 1024U)
#define MTK_FDT_MAX_MEMORY 16U
#define MTK_FDT_MAX_RESERVED 64U
#define MTK_FDT_MAX_EXCLUDED 64U
#define MTK_FDT_WINDOW_SIZE UINT64_C(0x20000000)
#define MTK_FDT_WINDOW_ALIGNMENT UINT64_C(0x200000)
enum mtk_fdt_reservation_kind { MTK_FDT_RESERVE_HEADER=1, MTK_FDT_RESERVE_REG=2, MTK_FDT_RESERVE_ALLOC=3 };
struct mtk_fdt_range { uint64_t base, size; };
/* Informational only. These fields never authorize display/pins/native I/O. */
struct mtk_fdt_framebuffer {
    uint64_t base, size;
    uint32_t width, height, stride, present;
    uint32_t found, fps; /* LE atag,videolfb only; present bit16. */
};
struct mtk_fdt_info {
    struct mtk_fdt_range memory[MTK_FDT_MAX_MEMORY];
    struct mtk_fdt_range reserved[MTK_FDT_MAX_RESERVED];
    uint8_t reserved_kind[MTK_FDT_MAX_RESERVED];
    uint32_t memory_count, reserved_count, total_size;
    uint32_t board_compatible; /* root exact mediatek,MT6765 or mediatek,MT6762 */
    struct mtk_fdt_framebuffer framebuffer;
};
enum mtk_fdt_error {
    MTK_FDT_OK = 0, MTK_FDT_E_HEADER = -1, MTK_FDT_E_BOUNDS = -2,
    MTK_FDT_E_STRUCTURE = -3, MTK_FDT_E_CELLS = -4,
    MTK_FDT_E_RANGE = -5, MTK_FDT_E_LIMIT = -6,
    MTK_FDT_E_AMBIGUOUS = -7, MTK_FDT_E_NO_WINDOW = -8
};
/* blob must name accessible_bytes readable bytes supplied by the bootloader.
 * On failure info is zeroed; successful parsing does not imply boot permission. */
int mtk_fdt_parse(const void *blob, size_t accessible_bytes, struct mtk_fdt_info *info);
/* fdt_pa is the physical address of this exact parsed FDT. excluded must include
 * every live source image, loader, stack, scratch area and other owned allocation.
 * Does not assume that the source blob is at an address inferred from the FDT. */
int mtk_fdt_select_window(const struct mtk_fdt_info *info, uint64_t fdt_pa,
    const struct mtk_fdt_range *excluded, size_t excluded_count, uint64_t *base);
/* Extend the validated low-address window through its containing RAM bank.
 * Stops before every reservation, live object, or the supplied CPU PA limit.
 * Keeps the existing low base so DMA buffers remain allocatable below4GiB.
 * The limit must be the exclusive upper physical address, not a RAM size. */
int mtk_fdt_expand_window(const struct mtk_fdt_info *info, uint64_t fdt_pa,
    const struct mtk_fdt_range *excluded, size_t excluded_count,
    uint64_t physical_limit, uint64_t *base, uint64_t *size);
/* Exact framebuffer reservation must be from memreserve/reg, not dynamic
 * allocation constraints, and the complete range must lie in one RAM bank. */
int mtk_fdt_framebuffer_reserved(const struct mtk_fdt_info *info);
const char *mtk_fdt_error_string(int error);
#endif
