/* SPDX-License-Identifier: MIT */
#include "psci_fdt.h"
#include "../fdt_handoff.h"
struct psci_node {unsigned kind,seen,reg;};
enum {OTHER,ROOT,CPUS,CPU,PSCI};
static uint32_t u32(const unsigned char *p)
{return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}
static void clear(void *p,size_t n){unsigned char *b=p;while(n--)*b++=0;}
static int same(const unsigned char *p,const char *s)
{while(*p&&*s&&*p==(unsigned char)*s){p++;s++;}return !*p&&!*s;}
static int string(const unsigned char *p,unsigned n,const char *s)
{unsigned i=0;while(s[i]){if(i>=n||p[i]!=(unsigned char)s[i])return 0;i++;}return n==i+1&&!p[i];}
static int cpu_name(const unsigned char *p)
{return p[0]=='c'&&p[1]=='p'&&p[2]=='u'&&p[3]=='@'&&p[4];}
static int mark(struct psci_node *n,unsigned bit)
{if(n->seen&bit)return -1;n->seen|=bit;return 0;}
int mtk_psci_fdt_topology(const void *blob,size_t accessible,uint64_t boot_mpidr,
    unsigned requested,struct mtk_psci_topology *out)
{
    struct mtk_fdt_info full;
    struct mtk_psci_topology result={0};
    struct psci_node stack[64];
    unsigned depth=0,cpus=0,psci=0,seen_cpus=0,cells_ok=0,psci_ok=0;
    const unsigned char *b=blob;
    if(!out)return -1;
    clear(out,sizeof(*out));
    if((requested!=2&&requested!=4&&requested!=8)||
        /* Only RES1 bit 31 and MT bit 24 may differ; reject U bit 30. */
        (boot_mpidr&~UINT64_C(0x81000000))||
        mtk_fdt_parse(blob,accessible,&full)||!full.board_compatible)return -1;
    /* Full parser above established bounded tokens, strings, reserve map,
     * nesting and property ranges. This pass adds CPU-specific constraints. */
    unsigned pos=u32(b+8),strings=u32(b+12),end=pos+u32(b+36);
    while(pos<end){
        unsigned token=u32(b+pos);pos+=4;
        if(token==1){
            const unsigned char *name=b+pos;
            unsigned kind=OTHER;
            if(!depth)kind=ROOT;
            else if(depth==1&&same(name,"cpus")){kind=CPUS;if(++cpus!=1)return -1;}
            else if(depth==1&&same(name,"psci")){kind=PSCI;if(++psci!=1)return -1;}
            else if(stack[depth-1].kind==CPUS&&cpu_name(name))kind=CPU;
            else if(stack[depth-1].kind==CPUS&&!same(name,"cpu-map")&&
                !same(name,"idle-states"))return -1;
            if(depth>=64||(depth&&stack[depth-1].kind==CPU))return -1;
            while(b[pos])pos++;
            pos=(pos+4)&~3u;
            stack[depth++]=(struct psci_node){.kind=kind};
        }else if(token==2){
            if(!depth)return -1;
            struct psci_node *n=&stack[--depth];
            if(n->kind==CPUS){if((n->seen&3)!=3)return -1;cells_ok=1;}
            if(n->kind==PSCI){if((n->seen&3)!=3)return -1;psci_ok=1;}
            if(n->kind==CPU){
                if((n->seen&15)!=15||n->reg&~0x103u||(n->reg&255)>3)return -1;
                unsigned index=((n->reg>>8)&1)*4+(n->reg&3),bit=1u<<index;
                if(seen_cpus&bit)return -1;
                seen_cpus|=bit;result.mpidr[index]=n->reg;++result.observed_count;
            }
        }else if(token==3){
            unsigned bytes=u32(b+pos),nameoff=u32(b+pos+4);pos+=8;
            const unsigned char *name=b+strings+nameoff,*v=b+pos;
            if(!depth)return -1;
            struct psci_node *n=&stack[depth-1];unsigned bit=0;
            if(n->kind==CPUS){
                if(same(name,"#address-cells")){bit=1;if(bytes!=4||u32(v)!=1)return -1;}
                else if(same(name,"#size-cells")){bit=2;if(bytes!=4||u32(v))return -1;}
                else if(same(name,"status")){bit=4;if(!string(v,bytes,"okay")&&!string(v,bytes,"ok"))return -1;}
            }else if(n->kind==CPU){
                if(same(name,"compatible")){bit=1;if(!string(v,bytes,"arm,cortex-a53"))return -1;}
                else if(same(name,"device_type")){bit=2;if(!string(v,bytes,"cpu"))return -1;}
                else if(same(name,"reg")){bit=4;if(bytes!=4)return -1;n->reg=u32(v);}
                else if(same(name,"enable-method")){bit=8;if(!string(v,bytes,"psci"))return -1;}
                else if(same(name,"status")){bit=16;if(!string(v,bytes,"okay")&&!string(v,bytes,"ok"))return -1;}
            }else if(n->kind==PSCI){
                if(same(name,"compatible")){bit=1;if(!string(v,bytes,"arm,psci-1.0"))return -1;}
                else if(same(name,"method")){bit=2;if(!string(v,bytes,"smc"))return -1;}
                else if(same(name,"status")){bit=4;if(!string(v,bytes,"okay")&&!string(v,bytes,"ok"))return -1;}
            }
            if(bit&&mark(n,bit))return -1;
            pos=(pos+bytes+3)&~3u;
        }else if(token==9)break;
        else if(token!=4)return -1;
    }
    if(depth||cpus!=1||psci!=1||!cells_ok||!psci_ok||seen_cpus!=255||result.observed_count!=8)return -1;
    result.count=requested;result.smc=1;
    for(unsigned i=requested;i<8;i++)result.mpidr[i]=0;
    *out=result;return 0;
}
