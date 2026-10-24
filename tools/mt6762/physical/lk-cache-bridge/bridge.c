/* Exact-LK cache admission. No MMIO, security-state or storage writes. */
typedef unsigned int u32;
typedef unsigned char u8;
#define SOURCE 0x48b00000u
#define LIMIT 0x08000000u
static u32 get32(const u8 *p) {
    return (u32)p[0] | (u32)p[1]<<8 | (u32)p[2]<<16 | (u32)p[3]<<24;
}
static int component(u32 size, u32 page, u32 total, u32 *position) {
    if (*position > total || size > total - *position) return 0;
    u32 end = *position + size;
    if (end > 0xffffffffu - (page - 1)) return 0;
    end = (end + page - 1) & ~(page - 1);
    if (end > total) return 0;
    *position = end;
    return 1;
}
__attribute__((used,noinline)) int bridge_prepare(const u8 *source, u32 size) {
    /* This particular cmd_boot supplies its transfer base in r7 and size in r9. */
    if ((u32)source != SOURCE || size < 1660 || size > LIMIT) return 0;
    if (get32(source) != 0x52444e41 || get32(source+4) != 0x2144494f) return 0;
    if (get32(source+40) != 2 || get32(source+1644) != 1660) return 0;
    u32 page = get32(source+36);
    if (page != 2048 && page != 4096 && page != 8192 && page != 16384) return 0;
    u32 position=page;
    u32 kernel=get32(source+8), ramdisk=get32(source+16), second=get32(source+24);
    u32 recovery=get32(source+1632), dtb=get32(source+1648);
    /* Diagnostic format supports a kernel plus DTB; no second-stage executable. */
    if (!kernel || !dtb || second) return 0;
    if (!component(kernel,page,size,&position) ||
        !component(ramdisk,page,size,&position) ||
        !component(second,page,size,&position)) return 0;
    /* Nonempty recovery DTBO must point to its actual serialized position. */
    if (recovery && (get32(source+1636)!=position || get32(source+1640))) return 0;
    if (!component(recovery,page,size,&position) ||
        !component(dtb,page,size,&position) || position!=size) return 0;
    /* Exact cache allocator owns/free-callbacks this new image as in normal boot. */
    void *(*allocate)(const char *,u32)=(void *)0x48037c51u;
    void *(*copy)(void *,const void *,u32)=(void *)0x48028e24u;
    void *image=allocate("boot",size);
    if (!image) return 0;
    copy(image,source,size);
    return 1;
}
