#include "conn_memory.h"

static void zero(void *p, size_t n) { unsigned char *b=p; while (n--) *b++=0; }
static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static uint64_t le64(const unsigned char *p) { return le32(p)|((uint64_t)le32(p+4)<<32); }
static uint32_t be32(const unsigned char *p) {
    return (uint32_t)p[3]|(uint32_t)p[2]<<8|(uint32_t)p[1]<<16|(uint32_t)p[0]<<24;
}
static uint64_t be64(const unsigned char *p) { return (uint64_t)be32(p)<<32|be32(p+4); }
static int equal(const char *a, const char *b) {
    while (*a && *a==*b) { a++; b++; } return *a==*b;
}
static int prefix(const char *a, const char *b) {
    while (*b) if (*a++!=*b++) return 0;
    return 1;
}
static int valid(struct mtk_fdt_range a) { return a.size && a.base<=UINT64_MAX-a.size; }
static int inside(struct mtk_fdt_range a, struct mtk_fdt_range b) {
    return valid(a) && valid(b) && a.base>=b.base && a.base+a.size<=b.base+b.size;
}
static int overlap(struct mtk_fdt_range a, struct mtk_fdt_range b) {
    return a.size && b.size && a.base<b.base+b.size && b.base<a.base+a.size;
}
static int covered(struct mtk_fdt_range a, const struct mtk_fdt_range *v, size_t n) {
    size_t i; for (i=0;i<n;i++) if (inside(a,v[i])) return 1;
    return 0;
}
static int parse_table(const unsigned char *b, size_t n,
    const struct mtk_fdt_range *banks, size_t bank_count, struct cm_table *t) {
    size_t i,j; uint32_t nf,nr;
    if (!b || !banks || !bank_count || bank_count>MTK_FDT_MAX_MEMORY) return CM_ARGUMENT;
    if (n!=CM_MBLOCK_BYTES || le32(b+3080)!=0x99999999 || le32(b+3084)!=2) return CM_FORMAT;
    nf=le32(b); nr=le32(b+3088);
    if (nf>CM_MAX_BLOCKS || nr>CM_MAX_BLOCKS) return CM_COUNT;
    for (i=0;i<bank_count;i++) {
        if (!valid(banks[i]) || t->bank_bytes>UINT64_MAX-banks[i].size) return CM_RANGE;
        for (j=0;j<i;j++) if (overlap(banks[i],banks[j])) return CM_OVERLAP;
        t->bank_bytes+=banks[i].size;
    }
    t->free_count=nf; t->reserved_count=nr;
    for (i=0;i<(size_t)nf+nr;i++) {
        int free_slot=i<nf; size_t k=free_slot?i:i-nf;
        const unsigned char *p=free_slot?b+8+k*24:b+3096+k*152;
        struct mtk_fdt_range a={le64(p),le64(p+8)};
        if (free_slot) {
            if (le32(p+16)>3) return CM_FORMAT; /* LK supports four DRAM ranks. */
            if (!a.size) {
                int in_bank=0;
                for (j=0;j<bank_count;j++)
                    if (a.base>=banks[j].base && a.base<=banks[j].base+banks[j].size) in_bank=1;
                if (!in_bank) return CM_RANGE;
                t->free[k]=a; continue;
            }
        } else {
            if (le32(p+16)>1) return CM_FORMAT; /* mapping flag, not a grant. */
            for (j=0;j<128 && p[20+j];j++)
                if (p[20+j]<32 || p[20+j]>126) return CM_FORMAT;
            if (!j || j==128) return CM_FORMAT;
        }
        if (!valid(a) || !covered(a,banks,bank_count)) return CM_RANGE;
        if (free_slot) { t->free[k]=a; t->free_bytes+=a.size; }
        else { t->reserved[k]=a; t->reserved_bytes+=a.size; }
        /* Every nonempty range must be disjoint, including across owner sets.
         * Therefore the running total cannot overflow the bank total. */
        for (j=0;j<i;j++) {
            struct mtk_fdt_range prev=j<nf?t->free[j]:t->reserved[j-nf];
            if (overlap(a,prev)) return CM_OVERLAP;
        }
    }
    if (t->free_bytes>t->bank_bytes || t->reserved_bytes!=t->bank_bytes-t->free_bytes)
        return CM_COVERAGE;
    return CM_OK;
}
int cm_parse_mblock(const void *bytes, size_t n, const struct mtk_fdt_range *banks,
    size_t bank_count, struct cm_table *out) {
    int e; if (!out) return CM_ARGUMENT;
    zero(out,sizeof(*out)); e=parse_table(bytes,n,banks,bank_count,out);
    if (e) zero(out,sizeof(*out));
    return e;
}

struct node_data {
    const unsigned char *alloc, *reg, *size, *align, *compat, *status;
    uint32_t alloc_n, reg_n, size_n, align_n, compat_n, status_n;
    unsigned int seen, no_map; int target;
};
static int string_value(const unsigned char *p, uint32_t n, const char *s) {
    uint32_t i=0; if (!p) return 0;
    while (s[i]) { if (i>=n || p[i]!=(unsigned char)s[i]) return 0; i++; }
    return n==i+1 && p[i]==0;
}
static int finish_node(struct node_data *d, struct cm_workspace *w, unsigned *targets) {
    uint32_t i,n; struct mtk_fdt_range *v; uint32_t *count;
    if (d->target>=0) {
        unsigned mask=1U<<(unsigned)d->target;
        uint64_t expected=d->target?CM_WIFI_BYTES:CM_CONSYS_BYTES;
        if (*targets&mask) return CM_OWNER;
        *targets|=mask;
        if (d->reg || !d->no_map || d->size_n!=8 || d->align_n!=8 ||
            be64(d->size)!=expected || be64(d->align)!=CM_ALIGNMENT ||
            !string_value(d->compat,d->compat_n,d->target?"shared-dma-pool":"mediatek,consys-reserve-memory") ||
            (d->status && !string_value(d->status,d->status_n,"okay") &&
             !string_value(d->status,d->status_n,"ok"))) return CM_OWNER;
        if (!d->alloc || !d->alloc_n || d->alloc_n%16) return CM_OWNER;
        v=w->allowed[d->target]; count=&w->allowed_count[d->target];
        n=d->alloc_n/16; if (n>CM_MAX_CONSTRAINTS) return CM_COUNT;
    } else {
        if (d->reg || !d->alloc) return CM_OK;
        v=w->other_dynamic; count=&w->other_count; n=d->alloc_n/16;
        if (!d->alloc_n || d->alloc_n%16 || n>64-*count) return CM_COUNT;
    }
    for (i=0;i<n;i++) {
        struct mtk_fdt_range a={be64(d->alloc+i*16),be64(d->alloc+i*16+8)};
        if (!valid(a)) return CM_RANGE;
        v[(*count)++]=a;
    }
    return CM_OK;
}
/* Called only after mtk_fdt_parse has validated every token, name and extent.
 * This pass preserves reserved child identity rather than subtracting ranges
 * by equality (an unrelated owner can have exactly the same alloc-ranges). */
static int extract(const unsigned char *b, struct cm_workspace *w) {
    uint32_t pos=be32(b+8), end=pos+be32(b+36), strings=be32(b+12);
    unsigned depth=0, targets=0; int reserved_root=0, memory_node=0, found=0;
    struct node_data d; zero(&d,sizeof(d)); d.target=-1;
    while (pos<end) {
        uint32_t token=be32(b+pos); pos+=4;
        if (token==1) {
            const char *name=(const char *)(b+pos); uint32_t len=0;
            while (b[pos+len]) len++;
            pos=(pos+len+4)&~3U; depth++;
            if (depth==2) {
                reserved_root=equal(name,"reserved-memory");
                memory_node=equal(name,"memory") || prefix(name,"memory@");
            }
            if (depth==3 && reserved_root) {
                zero(&d,sizeof(d)); d.target=-1;
                if (equal(name,"consys-reserve-memory")) d.target=0;
                if (equal(name,"wifi-reserve-memory")) d.target=1;
            }
        } else if (token==2) {
            if (depth==3 && reserved_root) { int e=finish_node(&d,w,&targets); if (e) return e; }
            if (depth==2) { reserved_root=0; memory_node=0; }
            depth--;
        } else if (token==3) {
            uint32_t n=be32(b+pos), nameoff=be32(b+pos+4); const unsigned char *p=b+pos+8;
            const char *name=(const char *)(b+strings+nameoff); unsigned bit=0;
            pos=(pos+8+n+3)&~3U;
            if (depth==2 && memory_node && equal(name,"mblock_info")) {
                int e; if (found++) return CM_OWNER;
                e=cm_parse_mblock(p,n,w->info.memory,w->info.memory_count,&w->table); if (e) return e;
            }
            if (depth!=3 || !reserved_root) continue;
            if (equal(name,"reg")) { bit=1; d.reg=p; d.reg_n=n; }
            else if (equal(name,"alloc-ranges") || equal(name,"alloc-range")) { bit=2; d.alloc=p; d.alloc_n=n; }
            else if (equal(name,"size")) { bit=4; d.size=p; d.size_n=n; }
            else if (equal(name,"alignment")) { bit=8; d.align=p; d.align_n=n; }
            else if (equal(name,"compatible")) { bit=16; d.compat=p; d.compat_n=n; }
            else if (equal(name,"status")) { bit=32; d.status=p; d.status_n=n; }
            else if (equal(name,"no-map")) { bit=64; if (n) return CM_OWNER; d.no_map=1; }
            else if (d.target>=0 && (equal(name,"reusable") || equal(name,"linux,cma-default") || equal(name,"linux,dma-default"))) return CM_OWNER;
            if (bit&d.seen) return CM_OWNER;
            d.seen|=bit;
        } else if (token==9) break;
    }
    return found==1 && targets==3?CM_OK:CM_OWNER;
}
static int available(struct mtk_fdt_range a, unsigned target,
    const struct cm_workspace *w, const struct cm_request *r, struct mtk_fdt_range selected) {
    size_t i; struct mtk_fdt_range dt={r->fdt_pa,w->info.total_size};
    if (!covered(a,w->table.free,w->table.free_count) ||
        !covered(a,w->allowed[target],w->allowed_count[target]) || overlap(a,selected) ||
        overlap(a,r->source_image) || overlap(a,r->kernel_managed) || overlap(a,r->loader_live) ||
        overlap(a,dt)) return 0;
    for (i=0;i<w->other_count;i++) if (overlap(a,w->other_dynamic[i])) return 0;
    for (i=0;i<r->additional_count;i++) if (overlap(a,r->additional[i])) return 0;
    if (w->info.framebuffer.present && w->info.framebuffer.size) {
        struct mtk_fdt_range fb={w->info.framebuffer.base,w->info.framebuffer.size};
        if (overlap(a,fb)) return 0;
    }
    return 1;
}
int cm_plan(const void *blob, size_t n, const struct cm_request *r,
    struct cm_workspace *w, struct cm_ledger *out) {
    size_t i; unsigned c,f; int e; struct mtk_fdt_range empty={0,0}, dt;
    if (!out) return CM_ARGUMENT;
    zero(out,sizeof(*out));
    if (!r || !w || !blob) return CM_ARGUMENT;
    if (r->enabled!=1) return CM_DISABLED;
    if (r->reserved_zero || !r->boot_nonce || r->additional_count>CM_MAX_EXTRA ||
        (r->additional_count && !r->additional) || !valid(r->source_image) ||
        !valid(r->kernel_managed) || !valid(r->loader_live)) return CM_ARGUMENT;
    for (i=0;i<r->additional_count;i++) if (!valid(r->additional[i])) return CM_RANGE;
    zero(w,sizeof(*w));
    if (mtk_fdt_parse(blob,n,&w->info) || !w->info.board_compatible) return CM_FDT;
    dt.base=r->fdt_pa; dt.size=w->info.total_size;
    if (!covered(dt,w->info.memory,w->info.memory_count) ||
        !covered(r->source_image,w->info.memory,w->info.memory_count) ||
        !covered(r->kernel_managed,w->info.memory,w->info.memory_count) ||
        !covered(r->loader_live,w->info.memory,w->info.memory_count)) return CM_RANGE;
    e=extract(blob,w); if (e) return e;
    /* Every actual fixed reservation must have LK ownership evidence. A new
     * fixed node overlapping advertised free space is an inconsistent handoff. */
    for (i=0;i<w->info.reserved_count;i++)
        if (w->info.reserved_kind[i]!=MTK_FDT_RESERVE_ALLOC &&
            !covered(w->info.reserved[i],w->table.reserved,w->table.reserved_count)) return CM_OWNER;
    /* Exhaustive bounded two-owner search below4GiB: at most256*256 pairs.
     * Backtracking prevents a greedy CONSYS choice from starving Wi-Fi. */
    for (c=0;c<256;c++) {
        struct mtk_fdt_range a={(uint64_t)c*CM_ALIGNMENT,CM_CONSYS_BYTES};
        if (!available(a,0,w,r,empty)) continue;
        for (f=0;f<256;f++) {
            struct mtk_fdt_range b={(uint64_t)f*CM_ALIGNMENT,CM_WIFI_BYTES};
            if (!available(b,1,w,r,a)) continue;
            out->version=1; out->count=2; out->boot_nonce=r->boot_nonce;
            out->fdt_pa=r->fdt_pa; out->fdt_bytes=w->info.total_size;
            out->proposed[0]=a; out->proposed[1]=b;
            out->bank_bytes=w->table.bank_bytes; out->free_bytes=w->table.free_bytes;
            out->lk_reserved_bytes=w->table.reserved_bytes;
            out->lk_free_count=w->table.free_count; out->lk_reserved_count=w->table.reserved_count;
            return CM_OK;
        }
    }
    return CM_NO_SPACE;
}
