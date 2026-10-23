/* MT6762 CPU/CCI clocks and SSPM table observation. No clock/voltage writes.
 * A stable table is not firmware liveness or permission to perform DVFS. */
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <sys/mt6762_platform.h>
#include <sys/mt6762_power.h>
#include <sys/mt6762_cpufreq.h>
#include <sys/mt6762_sspm.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include "mt6762_cpufreq_protocol.h"

static uintptr_t apmixed,mcucfg,csram;
static int started,clock_valid,table_valid,read_errors;
static int cpu0_khz=-1,cpu4_khz=-1,cci_khz=-1;
static int vproc_programmed_uv=-1,vsram_programmed_uv=-1;
static int cpu0_idx=-1,cpu4_idx=-1,cci_idx=-1;
static int cpu0_ceiling_khz=-1,cpu4_ceiling_khz=-1;
static int cpu0_table_uv=-1,cpu4_table_uv=-1,cci_table_uv=-1;
static int sspm_platform_alive;
static int dvfs_control_ready; /* Remains false: mailbox/liveness not established. */
SYSCTL_DECL(_kern_redwood);
#define CPU_SYSCTL(name,description) SYSCTL_INT(_kern_redwood,OID_AUTO,mt6762_##name,CTLFLAG_RD|CTLFLAG_LOCKED,&name,0,description)
CPU_SYSCTL(clock_valid,"Readback bits: CPU0=1 CPU4=2 CCI=4 VPROC=8 VSRAM=16");
CPU_SYSCTL(table_valid,"Stable C62 shared-table representation; not EEM/SSPM liveness proof");
CPU_SYSCTL(read_errors,"Native clock/table read failures");
CPU_SYSCTL(cpu0_khz,"CPU0-3 nominal PLL-derived kHz, -1 unknown");
CPU_SYSCTL(cpu4_khz,"CPU4-7 nominal PLL-derived kHz, -1 unknown");
CPU_SYSCTL(cci_khz,"CCI nominal PLL-derived kHz, -1 unknown");
CPU_SYSCTL(vproc_programmed_uv,"VPROC enabled/stable selector readback uV, not measured rail voltage");
CPU_SYSCTL(vsram_programmed_uv,"VSRAM enabled/stable selector readback uV, not measured rail voltage");
CPU_SYSCTL(cpu0_idx,"SSPM CPU0-3 reported index, -1 unavailable; no request acknowledgement implied");
CPU_SYSCTL(cpu4_idx,"SSPM CPU4-7 reported index, -1 unavailable; no request acknowledgement implied");
CPU_SYSCTL(cci_idx,"SSPM CCI reported index, -1 unavailable; no request acknowledgement implied");
CPU_SYSCTL(cpu0_ceiling_khz,"Shared PPM CPU0-3 frequency ceiling, -1 unknown; not a complete thermal budget");
CPU_SYSCTL(cpu4_ceiling_khz,"Shared PPM CPU4-7 frequency ceiling, -1 unknown; not a complete thermal budget");
CPU_SYSCTL(cpu0_table_uv,"Runtime table CPU0-3 voltage at reported index, -1 unknown");
CPU_SYSCTL(cpu4_table_uv,"Runtime table CPU4-7 voltage at reported index, -1 unknown");
CPU_SYSCTL(cci_table_uv,"Runtime table CCI voltage at reported index, -1 unknown");
CPU_SYSCTL(sspm_platform_alive,"Recent active PLATFORM response, not CPU-DVFS readiness");
CPU_SYSCTL(dvfs_control_ready,"DVFS control readiness; false until firmware ownership/liveness and thermal policy exist");
#undef CPU_SYSCTL

static int flag(const char *name)
{uint32_t v;return !mt6762_handoff_u32(name,&v) && v==1;}
static uint32_t rd(uintptr_t base,unsigned offset)
{
    uint32_t value=*(volatile uint32_t *)(base+offset);
    __asm__ volatile("dmb oshld":::"memory");
    return value;
}
static int rate(unsigned domain,int *result)
{
    static const unsigned con0[]={0x21c,0x20c,0x22c};
    static const unsigned div[]={0x7a0,0x7a4,0x7c0};
    uint32_t a[4],b[4],khz;
    for(unsigned attempt=0;attempt<3;attempt++) {
        a[0]=rd(apmixed,con0[domain]);a[1]=rd(apmixed,con0[domain]+4);
        a[2]=rd(apmixed,con0[domain]+12);a[3]=rd(mcucfg,div[domain]);
        b[0]=rd(apmixed,con0[domain]);b[1]=rd(apmixed,con0[domain]+4);
        b[2]=rd(apmixed,con0[domain]+12);b[3]=rd(mcucfg,div[domain]);
        if(!memcmp(a,b,sizeof(a)) && !mt6762_pll_khz(a[0],a[1],a[2],a[3],&khz)) {
            *result=(int)khz;return 0;
        }
    }
    return -1;
}
static int rails(void)
{
    static const uint16_t addr[]={0x14a2,0x14a4,0x19cc,0x19ce};
    uint16_t a[4],b[4];
    for(unsigned attempt=0;attempt<3;attempt++) {
        for(unsigned i=0;i<4;i++)if(mt6762_pwrap_read16(addr[i],&a[i]))return -1;
        for(unsigned i=0;i<4;i++)if(mt6762_pwrap_read16(addr[i],&b[i]))return -1;
        if(memcmp(a,b,sizeof(a)))continue;
        if((a[1]&3)==3) {vproc_programmed_uv=518750+(a[0]&127)*6250;clock_valid|=8;}
        if((a[3]&3)==3) {vsram_programmed_uv=518750+((a[2]>>8)&127)*6250;clock_valid|=16;}
        return 0;
    }
    return -1;
}
struct sspm_snapshot {
    uint32_t guards[5],words[144],eem[3],index[3],ppm[2];
};
static void snapshot(struct sspm_snapshot *s)
{
    for(unsigned i=0;i<4;i++)s->guards[i]=rd(csram,i*4);
    s->guards[4]=rd(csram,0x2a0);
    for(unsigned i=0;i<144;i++)s->words[i]=rd(csram,0x10+4*i);
    for(unsigned d=0;d<3;d++) {
        s->eem[d]=rd(csram,0x300+4*d);
        s->index[d]=rd(csram,0x354+4*d);
    }
    for(unsigned d=0;d<2;d++)s->ppm[d]=rd(csram,0x320+4*d);
}
static int table(void)
{
    struct sspm_snapshot a,b;
    struct mt6762_pvt_table t;
    unsigned ceiling[2],floor[2];
    for(unsigned attempt=0;attempt<3;attempt++) {
        snapshot(&a);snapshot(&b);
        if(memcmp(&a,&b,sizeof(a)))continue;
        if(a.guards[0]!=0x55aa55aa || a.guards[1]!=0xaa55aa55 ||
           a.guards[2]!=0x55aa55aa || a.guards[3]!=0xaa55aa55 ||
           a.guards[4]!=0x55aa55aa)return -1;
        for(unsigned d=0;d<3;d++)if(a.eem[d] || a.index[d]>15)return -1;
        if(mt6762_pvt_decode(a.words,&t))return -1;
        for(unsigned d=0;d<2;d++)if(mt6762_ppm_indices(a.ppm[d],&ceiling[d],&floor[d]))return -1;
        cpu0_idx=a.index[0];cpu4_idx=a.index[1];cci_idx=a.index[2];
        cpu0_table_uv=t.opp[0][cpu0_idx].uv;
        cpu4_table_uv=t.opp[1][cpu4_idx].uv;
        cci_table_uv=t.opp[2][cci_idx].uv;
        cpu0_ceiling_khz=t.opp[0][ceiling[0]].khz;
        cpu4_ceiling_khz=t.opp[1][ceiling[1]].khz;
        table_valid=1;return 0;
    }
    return -1;
}
static void poll(void)
{
    sspm_platform_alive=mt6762_sspm_alive_recent();
    clock_valid=table_valid=0;
    cpu0_khz=cpu4_khz=cci_khz=-1;
    vproc_programmed_uv=vsram_programmed_uv=-1;
    cpu0_idx=cpu4_idx=cci_idx=-1;
    cpu0_table_uv=cpu4_table_uv=cci_table_uv=-1;
    cpu0_ceiling_khz=cpu4_ceiling_khz=-1;
    if(!rate(0,&cpu0_khz))clock_valid|=1;else read_errors++;
    if(!rate(1,&cpu4_khz))clock_valid|=2;else read_errors++;
    if(!rate(2,&cci_khz))clock_valid|=4;else read_errors++;
    if(rails())read_errors++;
    if(csram && table())read_errors++;
}
static void worker(__unused void *parameter,__unused wait_result_t result)
{
    for(;;) {poll();delay_for_interval(1000,NSEC_PER_MSEC);}
}
void mt6762_cpufreq_init(void)
{
    uint32_t bin;
    thread_t thread;
    if(started || !mt6762_platform_ready() || !flag("cpu-clock-verified"))return;
    apmixed=(uintptr_t)mt6762_map_mmio(0x1000c000,0x1000);
    mcucfg=(uintptr_t)mt6762_map_mmio(0x10200000,0x1000);
    if(!apmixed || !mcucfg)return;
    if(flag("sspm-dvfs-verified") && !mt6762_handoff_u32("dvfs-bin",&bin) && bin==4)
        csram=(uintptr_t)mt6762_map_mmio(0x00110c00,0x1400);
    poll();
    printf("MT6762 CPU readback: valid=%#x L=%d LL=%d CCI=%d kHz VPROC=%d VSRAM=%d uV table=%d; DVFS control unavailable\n",
        clock_valid,cpu0_khz,cpu4_khz,cci_khz,vproc_programmed_uv,vsram_programmed_uv,table_valid);
    if(kernel_thread_start(worker,NULL,&thread)==KERN_SUCCESS) {
        started=1;thread_deallocate(thread);
    }
}
