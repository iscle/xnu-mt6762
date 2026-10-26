#include "fdt_handoff.h"
#define DEPTH_LIMIT 64U
#define BEGIN_NODE 1U
#define END_NODE 2U
#define PROP 3U
#define NOP 4U
#define END 9U
#define NONE 0U
#define ROOT 1U
#define RESERVED_ROOT 2U
#define RESERVED_CHILD 3U
#define CHOSEN 4U
#define FRAMEBUFFER 5U
struct node {
    uint32_t kind, ac, sc, seen_ac, seen_sc, children;
    uint32_t reg, reglen, have_reg, memory, disabled, seen_status;
    uint32_t seen_device_type, have_ranges, parent_ac, parent_sc;
    uint32_t tag_seen, high_seen, low_seen, size_seen, high, low, fbsize;
    uint32_t alloc, alloclen, have_alloc, compatible_seen;
    uint32_t properties, empty_zmc_placeholder;
    uint64_t tag_base; uint32_t tag_size, tag_found, tag_fps;
};
static uint32_t be32(const unsigned char *p)
{ return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3]; }
static uint32_t le32(const unsigned char *p)
{ return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static uint64_t be64(const unsigned char *p)
{ return ((uint64_t)be32(p)<<32)|be32(p+4); }
static void zero(void *p, size_t n)
{ unsigned char *b=p; while(n--) *b++=0; }
static int same(const unsigned char *a, const char *b)
{ while (*a && *b && *a==(unsigned char)*b) { ++a; ++b; } return !*a && !*b; }
static int basename_is(const unsigned char *a, const char *b)
{ while(*b && *a==(unsigned char)*b) { ++a; ++b; } return !*b && (!*a || *a=='@'); }
static int end_of(uint64_t start, uint64_t size, uint64_t *end)
{ if (!size || start > UINT64_MAX-size) return 0; *end=start+size; return 1; }
static int overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{ return a < b+m && b < a+n; }
static int bounded(uint32_t offset, uint32_t size, uint32_t total)
{ return offset<=total && size<=total-offset; }
static int terminated(const unsigned char *p, uint32_t remaining, uint32_t *len)
{ uint32_t i; for(i=0;i<remaining;++i) if(!p[i]) { *len=i; return 1; } return 0; }
static int add_range(struct mtk_fdt_info *i, int memory, unsigned kind, uint64_t base, uint64_t size)
{
    uint64_t end; uint32_t j;
    struct mtk_fdt_range *r=memory?i->memory:i->reserved;
    uint32_t *count=memory?&i->memory_count:&i->reserved_count;
    if(!end_of(base,size,&end)) return MTK_FDT_E_RANGE;
    if(*count >= (memory?MTK_FDT_MAX_MEMORY:MTK_FDT_MAX_RESERVED)) return MTK_FDT_E_LIMIT;
    if(memory) for(j=0;j<*count;++j) if(overlap(base,size,r[j].base,r[j].size)) return MTK_FDT_E_AMBIGUOUS;
    r[*count].base=base; r[*count].size=size;
    if(!memory) i->reserved_kind[*count]=(uint8_t)kind;
    ++*count;
    return 0;
}
static int finish_node(const unsigned char *b, struct node *n, struct mtk_fdt_info *i)
{
    uint32_t x; int rc;
    if(n->kind==ROOT) return n->ac==2 && n->sc==2 ? 0 : MTK_FDT_E_CELLS;
    if(n->kind==RESERVED_ROOT) {
        if(n->ac!=2 || n->sc!=2) return MTK_FDT_E_CELLS;
        return n->have_ranges ? 0 : MTK_FDT_E_STRUCTURE;
    }
    if(n->memory || n->kind==RESERVED_CHILD) {
        if(n->memory && n->disabled) return 0;
        if(n->parent_ac!=2 || n->parent_sc!=2) return MTK_FDT_E_CELLS;
        /* LK memory_lowpwer_fixup creates this node before looking for its
         * source allocation node and may leave it completely empty. With no
         * reg, size, properties or children it declares no reservation. Do
         * not extend this exception to populated or differently named nodes. */
        if(n->kind==RESERVED_CHILD && n->empty_zmc_placeholder &&
           !n->properties && !n->children) return 0;
        uint32_t offset=n->reg, length=n->reglen;
        if(!n->have_reg) {
            if(n->memory || !n->have_alloc) return MTK_FDT_E_RANGE;
            /* Exclude every possible allocation address, never guess which
             * dynamic reservation the bootloader/Linux allocator would choose. */
            offset=n->alloc; length=n->alloclen;
        }
        if(!length || length%16) return MTK_FDT_E_RANGE;
        for(x=0;x<length;x+=16) {
            rc=add_range(i,n->memory,n->have_reg?MTK_FDT_RESERVE_REG:MTK_FDT_RESERVE_ALLOC,be64(b+offset+x),be64(b+offset+x+8));
            if(rc) return rc;
        }
    }
    if(n->kind==CHOSEN) {
        uint64_t base=0,size=0,end; int have=0;
        if(n->high_seen || n->low_seen || n->size_seen) {
            if(!n->high_seen || !n->low_seen || !n->size_seen) return MTK_FDT_E_AMBIGUOUS;
            base=((uint64_t)n->high<<32)|n->low; size=n->fbsize; have=1;
        }
        if(n->tag_seen) {
            if(have && (base!=n->tag_base || size!=n->tag_size)) return MTK_FDT_E_AMBIGUOUS;
            base=n->tag_base; size=n->tag_size; have=1;
            i->framebuffer.found=n->tag_found; i->framebuffer.fps=n->tag_fps;
            i->framebuffer.present|=16U;
        }
        if(have && size) {
            if(!end_of(base,size,&end)) return MTK_FDT_E_RANGE;
            if((i->framebuffer.present&1U) && (i->framebuffer.base!=base || i->framebuffer.size!=size)) return MTK_FDT_E_AMBIGUOUS;
            i->framebuffer.base=base; i->framebuffer.size=size; i->framebuffer.present|=1U;
        } else if(have && ((i->framebuffer.present&1U) || n->tag_found)) return MTK_FDT_E_AMBIGUOUS;
    }
    if(n->kind==FRAMEBUFFER && n->have_reg) {
        if(n->parent_ac!=2 || n->parent_sc!=2) return MTK_FDT_E_CELLS;
        if(n->reglen!=16 || i->framebuffer.present&1U) return MTK_FDT_E_AMBIGUOUS;
        i->framebuffer.base=be64(b+n->reg); i->framebuffer.size=be64(b+n->reg+8);
        { uint64_t end; if(!end_of(i->framebuffer.base,i->framebuffer.size,&end)) return MTK_FDT_E_RANGE; }
        i->framebuffer.present|=1U;
    }
    return 0;
}
static int parse(const unsigned char *b, size_t accessible, struct mtk_fdt_info *i)
{
    uint32_t total, structure, structure_size, strings, strings_size, reserve, reserve_end;
    uint32_t at, stop, depth=0, root_seen=0, done=0, chosen_seen=0, reserved_seen=0, fb_seen=0;
    struct node nodes[DEPTH_LIMIT];
    if(!b || accessible<40 || be32(b)!=0xd00dfeedU) return MTK_FDT_E_HEADER;
    total=be32(b+4); structure=be32(b+8); strings=be32(b+12); reserve=be32(b+16);
    strings_size=be32(b+32); structure_size=be32(b+36);
    if(total<40 || total>MTK_FDT_MAX_SIZE || total>accessible || be32(b+20)!=17 || be32(b+24)>17)
        return MTK_FDT_E_HEADER;
    if(structure<40 || strings<40 || reserve<40 || (structure&3) || (reserve&7) ||
       !structure_size || (structure_size&3) || !bounded(structure,structure_size,total) ||
       !bounded(strings,strings_size,total) || overlap(structure,structure_size,strings,strings_size))
        return MTK_FDT_E_BOUNDS;
    reserve_end=reserve;
    for(;;) {
        uint64_t address,size; int rc;
        if(!bounded(reserve_end,16,total) || overlap(reserve_end,16,structure,structure_size) ||
           overlap(reserve_end,16,strings,strings_size)) return MTK_FDT_E_BOUNDS;
        address=be64(b+reserve_end); size=be64(b+reserve_end+8); reserve_end+=16;
        if(!address && !size) break;
        rc=add_range(i,0,MTK_FDT_RESERVE_HEADER,address,size); if(rc) return rc;
    }
    i->total_size=total; at=structure; stop=structure+structure_size;
    while(at<stop) {
        uint32_t token;
        if(!bounded(at,4,stop)) return MTK_FDT_E_BOUNDS;
        token=be32(b+at); at+=4;
        if(token==BEGIN_NODE) {
            uint32_t len, advance; struct node *n, *parent;
            if(done || depth>=DEPTH_LIMIT || !terminated(b+at,stop-at,&len)) return MTK_FDT_E_STRUCTURE;
            advance=(len+1U+3U)&~3U; if(!bounded(at,advance,stop)) return MTK_FDT_E_BOUNDS;
            if(!depth) { if(root_seen || len) return MTK_FDT_E_STRUCTURE; root_seen=1; }
            n=&nodes[depth]; zero(n,sizeof(*n)); n->ac=2; n->sc=1;
            if(!depth) n->kind=ROOT;
            else {
                parent=&nodes[depth-1]; parent->children=1;
                n->parent_ac=parent->ac; n->parent_sc=parent->sc;
                if(parent->kind==ROOT) {
                    if(basename_is(b+at,"memory")) n->memory=1;
                    else if(same(b+at,"reserved-memory")) { if(reserved_seen++) return MTK_FDT_E_AMBIGUOUS; n->kind=RESERVED_ROOT; }
                    else if(same(b+at,"chosen")) { if(chosen_seen++) return MTK_FDT_E_AMBIGUOUS; n->kind=CHOSEN; }
                } else if(parent->kind==RESERVED_ROOT) {
                    n->kind=RESERVED_CHILD;
                    n->empty_zmc_placeholder=same(b+at,"zone-movable-cma-memory");
                }
                else if(parent->kind==RESERVED_CHILD) return MTK_FDT_E_STRUCTURE;
                else if(parent->kind==CHOSEN && basename_is(b+at,"framebuffer")) {
                    if(fb_seen++) return MTK_FDT_E_AMBIGUOUS;
                    n->kind=FRAMEBUFFER;
                }
            }
            ++depth; at+=advance;
        } else if(token==END_NODE) {
            int rc; if(!depth) return MTK_FDT_E_STRUCTURE;
            rc=finish_node(b,&nodes[depth-1],i); if(rc) return rc;
            --depth;
        } else if(token==PROP) {
            uint32_t length,nameoff,len, padded; const unsigned char *name; struct node *n;
            if(!depth || !bounded(at,8,stop)) return MTK_FDT_E_STRUCTURE;
            n=&nodes[depth-1]; if(n->children) return MTK_FDT_E_STRUCTURE;
            ++n->properties;
            length=be32(b+at); nameoff=be32(b+at+4); at+=8;
            if(length>stop-at || nameoff>=strings_size || !terminated(b+strings+nameoff,strings_size-nameoff,&len)) return MTK_FDT_E_BOUNDS;
            padded=(length+3U)&~3U; if(padded<length || !bounded(at,padded,stop)) return MTK_FDT_E_BOUNDS;
            name=b+strings+nameoff;
            if(same(name,"#address-cells")) { if(n->seen_ac++ || length!=4) return MTK_FDT_E_CELLS; n->ac=be32(b+at); }
            else if(same(name,"#size-cells")) { if(n->seen_sc++ || length!=4) return MTK_FDT_E_CELLS; n->sc=be32(b+at); }
            else if(same(name,"reg")) { if(n->have_reg++) return MTK_FDT_E_AMBIGUOUS; n->reg=at; n->reglen=length; }
            else if(n->kind==RESERVED_CHILD && (same(name,"alloc-ranges") || same(name,"alloc-range"))) {
                if(n->have_alloc++) return MTK_FDT_E_AMBIGUOUS;
                n->alloc=at; n->alloclen=length;
            } else if(n->kind==ROOT && same(name,"compatible")) {
                uint32_t pos=0;
                if(n->compatible_seen++ || !length) return MTK_FDT_E_STRUCTURE;
                while(pos<length) {
                    uint32_t part;
                    if(!terminated(b+at+pos,length-pos,&part) || !part) return MTK_FDT_E_STRUCTURE;
                    if(same(b+at+pos,"mediatek,MT6765") || same(b+at+pos,"mediatek,MT6762")) i->board_compatible=1;
                    pos+=part+1;
                }
            }
            else if(same(name,"device_type")) {
                if(n->seen_device_type++ || !length || !terminated(b+at,length,&len) || len+1!=length) return MTK_FDT_E_STRUCTURE;
                if(same(b+at,"memory")) { if(depth!=2) return MTK_FDT_E_STRUCTURE; n->memory=1; }
                else if(n->memory) return MTK_FDT_E_AMBIGUOUS;
            } else if(same(name,"status")) {
                if(n->seen_status++ || !length || !terminated(b+at,length,&len) || len+1!=length) return MTK_FDT_E_STRUCTURE;
                n->disabled=!(same(b+at,"okay") || same(b+at,"ok"));
            } else if(same(name,"ranges") && n->kind==RESERVED_ROOT) {
                if(n->have_ranges++ || length) return MTK_FDT_E_STRUCTURE;
            } else if(n->kind==CHOSEN && same(name,"atag,videolfb")) {
                if(n->tag_seen++ || length<21 || (length&3) || !terminated(b+at+20,length-20,&len)) return MTK_FDT_E_STRUCTURE;
                n->tag_base=(uint64_t)le32(b+at)|((uint64_t)le32(b+at+4)<<32);
                n->tag_found=le32(b+at+8); n->tag_fps=le32(b+at+12); n->tag_size=le32(b+at+16);
            } else if(n->kind==CHOSEN && same(name,"videolfb-base_h")) {
                if(n->high_seen++ || length!=4) return MTK_FDT_E_AMBIGUOUS;
                n->high=be32(b+at);
            } else if(n->kind==CHOSEN && same(name,"videolfb-base_l")) {
                if(n->low_seen++ || length!=4) return MTK_FDT_E_AMBIGUOUS;
                n->low=be32(b+at);
            } else if(n->kind==CHOSEN && (same(name,"videolfb-vramSize") || same(name,"vramSize"))) {
                if(n->size_seen++ || length!=4) return MTK_FDT_E_AMBIGUOUS;
                n->fbsize=be32(b+at);
            } else if(n->kind==FRAMEBUFFER && (same(name,"width") || same(name,"height") || same(name,"stride"))) {
                uint32_t bit=same(name,"width")?2U:(same(name,"height")?4U:8U);
                if(length!=4 || i->framebuffer.present&bit) return MTK_FDT_E_AMBIGUOUS;
                if(bit==2) i->framebuffer.width=be32(b+at);
                if(bit==4) i->framebuffer.height=be32(b+at);
                if(bit==8) i->framebuffer.stride=be32(b+at);
                i->framebuffer.present|=bit;
            }
            at+=padded;
        } else if(token==NOP) { if(done) return MTK_FDT_E_STRUCTURE; }
        else if(token==END) {
            if(depth || !root_seen || done) return MTK_FDT_E_STRUCTURE;
            done=1; break;
        } else return MTK_FDT_E_STRUCTURE;
    }
    if(!done || !i->memory_count) return MTK_FDT_E_STRUCTURE;
    while(at<stop) if(b[at++]) return MTK_FDT_E_STRUCTURE;
    return 0;
}
int mtk_fdt_parse(const void *blob, size_t accessible, struct mtk_fdt_info *info)
{
    int rc; if(!info) return MTK_FDT_E_HEADER;
    zero(info,sizeof(*info)); rc=parse(blob,accessible,info); if(rc) zero(info,sizeof(*info)); return rc;
}
int mtk_fdt_select_window(const struct mtk_fdt_info *i, uint64_t fdt_pa,
    const struct mtk_fdt_range *excluded, size_t count, uint64_t *base)
{
    uint32_t bank,j; uint64_t end, candidate, limit, found=UINT64_MAX;
    if(!i || !base || !i->total_size || i->total_size>MTK_FDT_MAX_SIZE || !i->memory_count ||
       i->memory_count>MTK_FDT_MAX_MEMORY || i->reserved_count>MTK_FDT_MAX_RESERVED ||
       count>MTK_FDT_MAX_EXCLUDED || (count && !excluded)) return MTK_FDT_E_RANGE;
    *base=0;
    if(!end_of(fdt_pa,i->total_size,&end)) return MTK_FDT_E_RANGE;
    if((i->framebuffer.present&1U) && !end_of(i->framebuffer.base,i->framebuffer.size,&end)) return MTK_FDT_E_RANGE;
    for(j=0;j<i->reserved_count;++j) if(!end_of(i->reserved[j].base,i->reserved[j].size,&end)) return MTK_FDT_E_RANGE;
    for(j=0;j<count;++j) if(!end_of(excluded[j].base,excluded[j].size,&end)) return MTK_FDT_E_RANGE;
    for(bank=0;bank<i->memory_count;++bank) {
        if(!end_of(i->memory[bank].base,i->memory[bank].size,&end)) return MTK_FDT_E_RANGE;
        limit=end<UINT64_C(0x100000000)?end:UINT64_C(0x100000000);
        candidate=i->memory[bank].base>UINT64_C(0x80000000)?i->memory[bank].base:UINT64_C(0x80000000);
        if(candidate>UINT64_MAX-(MTK_FDT_WINDOW_ALIGNMENT-1)) continue;
        candidate=(candidate+MTK_FDT_WINDOW_ALIGNMENT-1)&~(MTK_FDT_WINDOW_ALIGNMENT-1);
        while(candidate<=limit && limit-candidate>=MTK_FDT_WINDOW_SIZE) {
            int used=overlap(candidate,MTK_FDT_WINDOW_SIZE,fdt_pa,i->total_size);
            if(!used && (i->framebuffer.present&1U)) used=overlap(candidate,MTK_FDT_WINDOW_SIZE,i->framebuffer.base,i->framebuffer.size);
            for(j=0;!used && j<i->reserved_count;++j) used=overlap(candidate,MTK_FDT_WINDOW_SIZE,i->reserved[j].base,i->reserved[j].size);
            for(j=0;!used && j<count;++j) used=overlap(candidate,MTK_FDT_WINDOW_SIZE,excluded[j].base,excluded[j].size);
            if(!used) { if(candidate<found) found=candidate; break; }
            candidate+=MTK_FDT_WINDOW_ALIGNMENT;
        }
    }
    if(found==UINT64_MAX) return MTK_FDT_E_NO_WINDOW;
    *base=found; return 0;
}
int mtk_fdt_expand_window(const struct mtk_fdt_info *i, uint64_t fdt_pa,
    const struct mtk_fdt_range *excluded, size_t count,
    uint64_t physical_limit, uint64_t *base, uint64_t *size)
{
    uint64_t selected, end=0;
    if(!base || !size)return MTK_FDT_E_RANGE;
    *base=0;*size=0;
    int error=mtk_fdt_select_window(i,fdt_pa,excluded,count,&selected);
    if(error)return error;
    for(unsigned n=0;n<i->memory_count;n++) {
        const struct mtk_fdt_range *r=&i->memory[n];
        if(selected>=r->base && selected<r->base+r->size) {
            /* Do not accept an ambiguous caller-created map either. */
            if(end)return MTK_FDT_E_AMBIGUOUS;
            end=r->base+r->size;
        }
    }
    if(end>physical_limit)end=physical_limit;
    if(fdt_pa>=selected && fdt_pa<end)end=fdt_pa;
    if((i->framebuffer.present&1U) && i->framebuffer.base>=selected &&
       i->framebuffer.base<end)end=i->framebuffer.base;
    for(unsigned n=0;n<i->reserved_count;n++)
        if(i->reserved[n].base>=selected && i->reserved[n].base<end)end=i->reserved[n].base;
    for(size_t n=0;n<count;n++)
        if(excluded[n].base>=selected && excluded[n].base<end)end=excluded[n].base;
    end&=~(MTK_FDT_WINDOW_ALIGNMENT-1);
    if(end<selected || end-selected<MTK_FDT_WINDOW_SIZE)return MTK_FDT_E_NO_WINDOW;
    *base=selected;*size=end-selected;
    return 0;
}
int mtk_fdt_framebuffer_reserved(const struct mtk_fdt_info *i)
{
    uint32_t n; uint64_t end, memory_end; int in_ram=0;
    if(!i || !(i->framebuffer.present&1U) || i->memory_count>MTK_FDT_MAX_MEMORY ||
       i->reserved_count>MTK_FDT_MAX_RESERVED ||
       !end_of(i->framebuffer.base,i->framebuffer.size,&end)) return 0;
    for(n=0;n<i->memory_count;++n) {
        if(!end_of(i->memory[n].base,i->memory[n].size,&memory_end)) return 0;
        if(i->framebuffer.base>=i->memory[n].base && end<=memory_end) in_ram=1;
    }
    if(!in_ram) return 0;
    for(n=0;n<i->reserved_count;++n)
        if((i->reserved_kind[n]==MTK_FDT_RESERVE_HEADER || i->reserved_kind[n]==MTK_FDT_RESERVE_REG) &&
           i->reserved[n].base==i->framebuffer.base && i->reserved[n].size==i->framebuffer.size) return 1;
    return 0;
}
const char *mtk_fdt_error_string(int e)
{
    switch(e) {
    case 0:return "ok"; case -1:return "header"; case -2:return "bounds";
    case -3:return "structure"; case -4:return "cells"; case -5:return "range";
    case -6:return "limit"; case -7:return "ambiguous"; case -8:return "no-window";
    default:return "unknown";
    }
}
