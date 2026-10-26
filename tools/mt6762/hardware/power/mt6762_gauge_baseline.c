#include "mt6762_gauge_baseline.h"
#define E_HEADER MT6762_GAUGE_BASELINE_E_HEADER
#define E_BOUNDS MT6762_GAUGE_BASELINE_E_BOUNDS
#define E_STRUCTURE MT6762_GAUGE_BASELINE_E_STRUCTURE
#define E_AMBIGUOUS MT6762_GAUGE_BASELINE_E_AMBIGUOUS
#define E_PROFILE MT6762_GAUGE_BASELINE_E_PROFILE
#define E_DISABLED MT6762_GAUGE_BASELINE_E_DISABLED
#define E_LIMIT MT6762_GAUGE_BASELINE_E_LIMIT
#define MAX_DEPTH 64u
#define SEEN_COMPATIBLE 1u
#define SEEN_STATUS 2u
#define SEEN_RFG 4u
#define SEEN_TUNE 8u
struct baseline_node {unsigned path,seen,children;};
static uint32_t be32(const unsigned char *p)
{return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
static uint64_t be64(const unsigned char *p)
{return ((uint64_t)be32(p)<<32)|be32(p+4);}
static int bounded(uint32_t at,uint32_t size,uint32_t end)
{return at<=end && size<=end-at;}
static int overlap(uint32_t a,uint32_t n,uint32_t b,uint32_t m)
{return n && m && a<b+m && b<a+n;}
static int length(const unsigned char *p,uint32_t maximum,uint32_t *out)
{for(uint32_t n=0;n<maximum;n++)if(!p[n]){*out=n;return 1;}return 0;}
static int same(const unsigned char *p,const char *s)
{while(*p && *s && *p==(unsigned char)*s){p++;s++;}return !*p && !*s;}
static int bytes_equal(const unsigned char *a,uint32_t n,const char *b,uint32_t m)
{if(n!=m)return 0;for(uint32_t i=0;i<n;i++)if(a[i]!=(unsigned char)b[i])return 0;return 1;}
static int compatible(unsigned path,const unsigned char *value,uint32_t size)
{
    static const char root[]="mediatek,MT6765";
    static const char pwrap[]="mediatek,mt6765-pwrap\0syscon";
    static const char pmic[]="mediatek,mt6357";
    static const char gauge[]="mediatek,mt6357-gauge";
    switch(path) {
    case 1:return bytes_equal(value,size,root,sizeof(root));
    case 2:return bytes_equal(value,size,pwrap,sizeof(pwrap));
    case 3:return bytes_equal(value,size,pmic,sizeof(pmic));
    case 4:return bytes_equal(value,size,gauge,sizeof(gauge));
    default:return 1;
    }
}
static int parse(const unsigned char *b,size_t accessible,
    struct mt6762_gauge_baseline *next)
{
    static const char *const names[]={"","pwrap@1000d000","main_pmic","mtk_gauge"};
    struct baseline_node stack[MAX_DEPTH];
    unsigned depth=0,root_seen=0,seen_path[4]={0},gauge_compatible=0,done=0;
    uint32_t total,structure,structure_size,strings,strings_size,reserve,at,stop;
    if(!b || accessible<40 || be32(b)!=0xd00dfeed)return E_HEADER;
    total=be32(b+4);structure=be32(b+8);strings=be32(b+12);reserve=be32(b+16);
    strings_size=be32(b+32);structure_size=be32(b+36);
    if(total<40 || total>accessible || total>MT6762_GAUGE_BASELINE_MAX_FDT ||
       be32(b+20)!=17 || be32(b+24)<16 || be32(b+24)>17)return E_HEADER;
    if(structure<40 || strings<40 || reserve<40 || (structure&3) || (reserve&7) ||
       !structure_size || (structure_size&3) || !strings_size ||
       !bounded(structure,structure_size,total) || !bounded(strings,strings_size,total) ||
       overlap(structure,structure_size,strings,strings_size))return E_BOUNDS;
    /* Validate the reserve-map terminator and separation from other blocks;
     * do not interpret reservations as permission for this read-only query. */
    at=reserve;
    for(unsigned count=0;;count++) {
        uint64_t address,size;
        if(count>=256)return E_LIMIT;
        if(!bounded(at,16,total) || overlap(at,16,structure,structure_size) ||
           overlap(at,16,strings,strings_size))return E_BOUNDS;
        address=be64(b+at);size=be64(b+at+8);at+=16;
        if(!address && !size)break;
        if(!size || address>UINT64_MAX-size)return E_BOUNDS;
    }
    at=structure;stop=structure+structure_size;
    while(at<stop) {
        uint32_t token;
        if(!bounded(at,4,stop))return E_BOUNDS;
        token=be32(b+at);at+=4;
        if(token==1) {
            uint32_t size,advance;unsigned path=0;
            if(depth>=MAX_DEPTH)return E_LIMIT;
            if(!length(b+at,stop-at,&size))return E_STRUCTURE;
            advance=(size+4u)&~3u;
            if(!bounded(at,advance,stop))return E_BOUNDS;
            if(!depth) {
                if(root_seen++ || size)return E_STRUCTURE;
                path=1;
            }else {
                if(!size)return E_STRUCTURE;
                for(uint32_t i=0;i<size;i++)if(b[at+i]=='/')return E_STRUCTURE;
                stack[depth-1].children=1;
                if(depth<4 && stack[depth-1].path==depth && same(b+at,names[depth]))path=depth+1;
            }
            if(path && seen_path[path-1]++)return E_AMBIGUOUS;
            stack[depth++]=(struct baseline_node){path,0,0};at+=advance;
        }else if(token==2) {
            struct baseline_node *node;
            if(!depth)return E_STRUCTURE;
            node=&stack[--depth];
            if(node->path && !(node->seen&SEEN_COMPATIBLE))return E_PROFILE;
            if(node->path==4 && (node->seen&(SEEN_RFG|SEEN_TUNE))!=(SEEN_RFG|SEEN_TUNE))return E_PROFILE;
        }else if(token==3) {
            struct baseline_node *node;
            uint32_t size,nameoff,n,padded,bit=0;const unsigned char *name;
            if(!depth || !bounded(at,8,stop))return E_STRUCTURE;
            node=&stack[depth-1];if(node->children)return E_STRUCTURE;
            size=be32(b+at);nameoff=be32(b+at+4);at+=8;
            if(size>stop-at || nameoff>=strings_size ||
               !length(b+strings+nameoff,strings_size-nameoff,&n) || !n)return E_BOUNDS;
            padded=(size+3u)&~3u;
            if(padded<size || !bounded(at,padded,stop))return E_BOUNDS;
            name=b+strings+nameoff;
            if(same(name,"compatible"))bit=SEEN_COMPATIBLE;
            else if(same(name,"status"))bit=SEEN_STATUS;
            else if(node->path==4 && same(name,"R_FG_VALUE"))bit=SEEN_RFG;
            else if(node->path==4 && same(name,"CAR_TUNE_VALUE"))bit=SEEN_TUNE;
            if(bit && (node->seen&bit))return E_AMBIGUOUS;
            node->seen|=bit;
            if(bit==SEEN_COMPATIBLE) {
                uint32_t pos=0;
                if(!size)return E_STRUCTURE;
                while(pos<size) {
                    if(!length(b+at+pos,size-pos,&n) || !n)return E_STRUCTURE;
                    if(same(b+at+pos,"mediatek,mt6357-gauge") && ++gauge_compatible>1)return E_AMBIGUOUS;
                    pos+=n+1;
                }
                if(!compatible(node->path,b+at,size))return E_PROFILE;
            }else if(bit==SEEN_STATUS) {
                if(!size || !length(b+at,size,&n) || n+1!=size)return E_STRUCTURE;
                if(node->path && !same(b+at,"okay") && !same(b+at,"ok"))return E_DISABLED;
            }else if(bit==SEEN_RFG || bit==SEEN_TUNE) {
                if(size!=4)return E_PROFILE;
                if(bit==SEEN_RFG)next->dt_r_fg=be32(b+at);
                else next->dt_car_tune=be32(b+at);
            }
            at+=padded;
        }else if(token==4)continue;
        else if(token==9) {
            if(depth || root_seen!=1)return E_STRUCTURE;
            done=1;break;
        }else return E_STRUCTURE;
    }
    if(!done)return E_STRUCTURE;
    while(at<stop)if(b[at++])return E_STRUCTURE;
    if(seen_path[3]!=1 || gauge_compatible!=1 ||
       next->dt_r_fg!=10 || next->dt_car_tune!=100)return E_PROFILE;
    next->version=MT6762_GAUGE_BASELINE_V1;next->fdt_size=total;
    next->r_fg=next->dt_r_fg*10;next->car_tune=next->dt_car_tune*10;
    return 0;
}
int mt6762_gauge_baseline_from_fdt(const void *blob,size_t accessible,
    struct mt6762_gauge_baseline *out)
{
    struct mt6762_gauge_baseline next={0};int error;
    if(!out)return E_HEADER;
    *out=next;
    error=parse(blob,accessible,&next);
    if(!error)*out=next;
    return error;
}
