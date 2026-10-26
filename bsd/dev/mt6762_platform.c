/* MT6762 native peripheral foundation. Boot handoff contract: doc/mt6762-native.md.
 * No MMIO is touched without the explicit versioned native handoff. */
#include <sys/mt6762_platform.h>
#if defined(ARM64_BOARD_CONFIG_MT6762)
#include <sys/mt6762_i2c.h>
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <kern/sched_prim.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <mach/vm_param.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <sys/systm.h>
#include <vm/vm_kern.h>
extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern uint64_t kvtophys(vm_offset_t);
extern kern_return_t thread_terminate(thread_t);
#include "../../tools/mt6762/hardware/display-touch/mt6762_touch_entry.h"

static int ready;
static DTEntry handoff;
static uintptr_t top, infra, gpio, pll, gic;
static uint32_t parent_index, parent_hz;
static LCK_GRP_DECLARE(mt6762_i2c_group,"mt6762-i2c");
static LCK_MTX_DECLARE(mt6762_i2c_lock,&mt6762_i2c_group);
static LCK_MTX_DECLARE(mt6762_attach_lock,&mt6762_i2c_group);
static int attached, initialized;
struct native_bus { struct mtk_i2c_v2 engine; uintptr_t base,dma,dma_page; unsigned id; size_t dma_used; };
static struct native_bus buses[2];

static int property(const char *name, void *out, unsigned size)
{
    const void *value;
    unsigned length=0;
    if (!handoff || !name || !out ||
        SecureDTGetProperty(handoff,name,&value,&length)!=kSuccess || length!=size)
        return -1;
    memcpy(out,value,size); /* ADT scalars are little endian, unlike FDT. */
    return 0;
}
int mt6762_handoff_u32(const char *name,uint32_t *out) {return property(name,out,4);}
int mt6762_handoff_u64(const char *name,uint64_t *out) {return property(name,out,8);}
static int flag(const char *name) {uint32_t v;return !mt6762_handoff_u32(name,&v)&&v==1;}
int mt6762_platform_ready(void) {return __atomic_load_n(&ready,__ATOMIC_ACQUIRE);}

void *mt6762_map_mmio(uint64_t pa,size_t bytes)
{
    static const struct {uint64_t base,size;} regions[]={
        {0x00110c00,0x1400}, /* DVFS shared SRAM; consumer requires its own verified gate. */
        {0x10000000,0x2000}, {0x10005000,0x2000}, {0x1000c000,0x2000},
        {0x10007000,0x1000}, {0x1000b000,0x1000}, /* Separately admitted watchdog/EINT observation. */
        {0x10002000,0x1000}, /* MSDC electrical pads; owned inherited state only. */
        {0x11230000,0x10000}, {0x11cd0000,0x1000}, /* MSDC0 and trained timing macro. */
        {0x10010000,0x1000}, {0x10200000,0x1000},
        {0x10450000,0x100}, {0x10451000,8}, /* SSPM mailbox0, explicit ownership only. */
        {0x11000000,0x1000}, {0x11007000,0x1000}, {0x11016000,0x1000},
        {0x1100b000,0x1000}, {0x11c50190,12}, /* Thermal controller/efuse, separately admitted. */
        {0x1100e000,0x1000}, {0x14000000,0x1000},
        {0x1400b000,0x1000}, {0x1400d000,0x1000}, {0x14014000,0x1000},
        {0x0c000000,0x40000}
    };
    if (!ready || !bytes) return NULL;
    for (unsigned i=0;i<sizeof(regions)/sizeof(regions[0]);i++) {
        if (pa>=regions[i].base && pa-regions[i].base<regions[i].size &&
            bytes<=regions[i].size-(pa-regions[i].base))
            return (void *)ml_io_map((vm_offset_t)pa,(vm_size_t)bytes);
    }
    return NULL;
}
static uint32_t r32(uintptr_t p,unsigned o) {return *(volatile uint32_t *)(p+o);}
static void w32(uintptr_t p,unsigned o,uint32_t v) {*(volatile uint32_t *)(p+o)=v;__asm__ volatile("dsb sy":::"memory");}
static uint16_t br16(void *p,unsigned o) {struct native_bus *b=p;return *(volatile uint16_t *)(b->base+o);}
static void bw16(void *p,unsigned o,uint16_t v) {struct native_bus *b=p;*(volatile uint16_t *)(b->base+o)=v;}
static uint32_t dr32(void *p,unsigned o) {return r32(((struct native_bus *)p)->dma,o);}
static void dw32(void *p,unsigned o,uint32_t v) {w32(((struct native_bus *)p)->dma,o,v);}
static void barrier(void *p) {(void)p;__asm__ volatile("dsb sy":::"memory");}
static void wait_us(void *p,unsigned us) {(void)p;delay_for_interval(us,NSEC_PER_USEC);}

/* Private full VM page: no cache lines can overlap another owner's allocation.
 * Keep this page pinned forever after a DMA error. No reset/reuse guessing. */
static void dma_to_device(void *p,size_t tx,size_t rx)
{
    struct native_bus *b=p;
    b->dma_used=tx>rx?tx:rx;
    uint8_t *page=(void *)b->dma_page;
    for(size_t i=0;i<64;i++)page[i]=0xa5;
    for(size_t i=64+b->dma_used;i<PAGE_SIZE;i++)page[i]=0xa5;
    for (uintptr_t va=b->dma_page;va<b->dma_page+PAGE_SIZE;va+=64)
        __asm__ volatile("dc civac, %0"::"r"(va):"memory");
    barrier(p);
}
static void dma_to_cpu(void *p,size_t rx)
{
    struct native_bus *b=p;
    if (rx) for (uintptr_t va=b->dma_page;va<b->dma_page+PAGE_SIZE;va+=64)
        __asm__ volatile("dc ivac, %0"::"r"(va):"memory");
    barrier(p);
    uint8_t *page=(void *)b->dma_page;
    for(size_t i=0;i<PAGE_SIZE;i++)if((i<64 || i>=64+b->dma_used) && page[i]!=0xa5) {
        b->engine.faulted=1;
        kprintf("MT6762_I2C_DMA canary failure bus=%u offset=%lu\n",b->id,i);
        break;
    }
}
static unsigned pin_mode(unsigned pin)
{return (r32(gpio,0x300+(pin/8)*16)>>((pin%8)*4))&15;}
int mt6762_gpio_input(unsigned pin,unsigned *level)
{
    if (!ready || !gpio || !level || pin>=179 || pin_mode(pin)!=0 ||
        (r32(gpio,(pin/32)*16)&(1u<<(pin%32)))) return -1;
    *level=(r32(gpio,0x200+(pin/32)*16)>>(pin%32))&1;
    return 0;
}
static int clock_rate(uint32_t *hz)
{
    if (!top || (r32(top,0xa0)&7)!=parent_index) return -1;
    if (!parent_index) return mtk_i2c_parent_rate(0,0,0,0,hz);
    if (!pll) return -1;
    unsigned off=parent_index<=2 ? 0x26c : 0x23c;
    uint32_t c0=r32(pll,off),c1=r32(pll,off+4),power=r32(pll,off+12);
    barrier(NULL);
    if (c0!=r32(pll,off) || c1!=r32(pll,off+4) || power!=r32(pll,off+12)) return -1;
    return mtk_i2c_parent_rate(parent_index,c0,c1,power,hz);
}
static int clocks_stable(void)
{
    uint32_t hz;
    return !clock_rate(&hz) && hz==parent_hz && !(r32(top,0xa0)&0x80) &&
        !(r32(infra,0x90)&(1u<<11)) && !(r32(infra,0x94)&(1u<<18));
}
static void initialize_bus(struct native_bus *b,unsigned id)
{
    struct mtk_i2c_timing timing;
    uint32_t hz;
    unsigned scl=id==0 ? 83 : 48,sda=id==0 ? 82 : 49,irq=id==0 ? 116 : 162;
    const char *verified=id==0 ? "i2c0-verified" : "i2c5-verified";
    if (!flag(verified)) return;
    if (mt6762_handoff_u32(id==0 ? "i2c0-hz" : "i2c5-hz",&hz) ||
        mtk_i2c_v2_timing(parent_hz,5,hz,&timing) ||
        pin_mode(scl)!=1 || pin_mode(sda)!=1) {
        printf("MT6762: I2C%u rejected timing or pinmux\n",id);return;
    }
    b->id=id;
    b->base=(uintptr_t)mt6762_map_mmio(id==0 ? 0x11007000 : 0x11016000,0x1000);
    b->dma=(uintptr_t)mt6762_map_mmio(id==0 ? 0x11000080 : 0x11000580,0x80);
    if (!b->base || !b->dma || (br16(b,0x24)&1) || dr32(b,8)) {
        printf("MT6762: I2C%u absent or busy at handoff\n",id);return;
    }
    /* Peripheral IRQ stays masked in GIC throughout this polling implementation. */
    w32(gic,0x180+(irq/32)*4,1u<<(irq%32));
    unsigned poll;
    for (poll=0;poll<10000;poll++) {
        if (!(r32(gic,0)&0x80000000u) &&
            !(r32(gic,0x100+(irq/32)*4)&(1u<<(irq%32)))) break;
        wait_us(NULL,1);
    }
    if (poll==10000) {
        printf("MT6762: I2C%u GIC interrupt mask did not complete\n",id);return;
    }
    vm_offset_t memory=0;
    /* First physical APDMA path stays below4GiB; high-bit routing has not
     * been measured. VM ppnum units follow PAGE_SHIFT, not the4KiB PTE size. */
    ppnum_t dma_max_page=(ppnum_t)((UINT64_C(0x100000000)>>PAGE_SHIFT)-1);
    if (kmem_alloc_contig(kernel_map,&memory,PAGE_SIZE,PAGE_MASK,dma_max_page,0,
        KMA_KOBJECT|KMA_ZERO|KMA_DATA,VM_KERN_MEMORY_IOKIT)!=KERN_SUCCESS) return;
    uint64_t physical=kvtophys(memory);
    if (!physical || physical>=UINT64_C(0x100000000) || PAGE_SIZE>UINT64_C(0x100000000)-physical) {
        kmem_free(kernel_map,memory,PAGE_SIZE);return;
    }
    b->dma_page=memory;
    b->engine=(struct mtk_i2c_v2){.context=b,.read16=br16,.write16=bw16,
        .dma_read32=dr32,.dma_write32=dw32,.barrier=barrier,.delay_us=wait_us,
        .dma_sync_device=dma_to_device,.dma_sync_cpu=dma_to_cpu,
        .dma_buffer=(uint8_t *)memory+64,.dma_address=physical+64,.dma_capacity=PAGE_SIZE-128,
        .timeout_us=10000,.bus_hz=hz};
    bw16(b,8,0);bw16(b,0xc,0x1ff);bw16(b,0x38,1);
    bw16(b,0x48,timing.clock_div);bw16(b,0x20,timing.timing);
    bw16(b,0x2c,timing.ltiming);bw16(b,0x30,0);bw16(b,0x28,timing.ext);
    bw16(b,0x34,3);bw16(b,0x1c,0xa);bw16(b,0x4c,timing.timeout);
    barrier(b);
    /* Capture every readback before deciding: short-circuit comparisons hid
     * the first physical setup failure from the retained no-UART log. */
    uint16_t actual_div=br16(b,0x48),actual_timing=br16(b,0x20);
    uint16_t actual_ltiming=br16(b,0x2c),actual_hs=br16(b,0x30);
    uint16_t actual_io=br16(b,0x34),actual_ext=br16(b,0x28);
    uint16_t actual_delay=br16(b,0x1c),actual_timeout=br16(b,0x4c);
    int stable=clocks_stable();
    kprintf("MT6762_I2C_SETUP bus=%u div=%x/%x timing=%x/%x ltiming=%x/%x hs=%x/0 io=%x/3 clocks=%u\n",
        id,actual_div,timing.clock_div,actual_timing,timing.timing,
        actual_ltiming,timing.ltiming,actual_hs,actual_io,stable);
    kprintf("MT6762_I2C_SETUP_AUX bus=%u ext=%x/%x delay=%x/a timeout=%x/%x top=%x infra0=%x infra1=%x\n",
        id,actual_ext,timing.ext,actual_delay,actual_timeout,timing.timeout,
        r32(top,0xa0),r32(infra,0x90),r32(infra,0x94));
    if (actual_div!=timing.clock_div || actual_timing!=timing.timing ||
        actual_ltiming!=timing.ltiming || actual_hs || actual_io!=3 || !stable) {
        b->engine.faulted=1;printf("MT6762: I2C%u setup readback failed\n",id);return;
    }
    b->engine.initialized=1;
    printf("MT6762: native I2C%u ready parent=%uHz bus=%uHz DMA=0x%llx\n",id,parent_hz,hz,physical);
    kprintf("MT6762_I2C_READY bus=%u parent=%u hz=%u dma=%llx\n",id,parent_hz,hz,physical+64);
}
static uintptr_t entry_maps[MT6762_TOUCH_ENTRY_REGIONS];
static uint32_t entry_read(void *unused,uint32_t address,unsigned width)
{
    (void)unused;
    for(unsigned i=0;i<MT6762_TOUCH_ENTRY_REGIONS;i++) {
        uint32_t base=mt6762_touch_entry_base(i);
        if(address<base || address-base>=0x1000)continue;
        uintptr_t p=entry_maps[i]+address-base;
        uint32_t value=width==2?*(volatile uint16_t *)p:*(volatile uint32_t *)p;
        barrier(NULL);return value;
    }
    return UINT32_MAX;
}
static int touch_entry_check(void)
{
    for(unsigned i=0;i<MT6762_TOUCH_ENTRY_REGIONS;i++) {
        uint32_t base=mt6762_touch_entry_base(i);
        entry_maps[i]=(uintptr_t)mt6762_map_mmio(base,0x1000);
        if(!entry_maps[i]) {
            kprintf("MT6762_TOUCH_ENTRY mapping failed address=%x\n",base);return 0;
        }
    }
    struct mt6762_touch_entry_failure failure;
    if(mt6762_touch_entry_detail(entry_read,NULL,&failure))return 1;
    kprintf("MT6762_TOUCH_ENTRY mismatch address=%x width=%u pass=%u value=%x mask=%x expected=%x\n",
        failure.address,failure.width,failure.pass,failure.actual,failure.mask,failure.expected);
    return 0;
}
int mt6762_i2c_ready(unsigned bus)
{
    if (bus!=0 && bus!=5) return 0;
    struct native_bus *b=&buses[bus==5];
    return ready && b->engine.initialized && !b->engine.faulted;
}
int mt6762_i2c_transfer(unsigned bus,unsigned addr,const void *tx,size_t nt,void *rx,size_t nr)
{
    if ((bus!=0 && bus!=5) || addr<8 || addr>0x77 || (!nt && !nr) ||
        nt>4096 || nr>4096 || (nt && !tx) || (nr && !rx)) return -1;
    struct native_bus *b=&buses[bus==5];
    struct mtk_i2c_msg msgs[2];unsigned n=0;
    if (nt) msgs[n++]=(struct mtk_i2c_msg){(uint8_t)addr,0,(uint16_t)nt,(uint8_t *)tx};
    if (nr) msgs[n++]=(struct mtk_i2c_msg){(uint8_t)addr,1,(uint16_t)nr,rx};
    lck_mtx_lock(&mt6762_i2c_lock);
    int result=-1;
    if (mt6762_i2c_ready(bus)) {
        if (!clocks_stable()) b->engine.faulted=1;
        else {result=mtk_i2c_v2_transfer(&b->engine,msgs,n);if (b->engine.faulted)result=-1;else if(result==(int)n)result=0;}
    }
    lck_mtx_unlock(&mt6762_i2c_lock);
    return result;
}
void mt6762_platform_attach(void)
{
    uint32_t version;
    lck_mtx_lock(&mt6762_attach_lock);
    if (attached) {lck_mtx_unlock(&mt6762_attach_lock);return;}
    attached=1;
    if (SecureDTLookupEntry(NULL,"/chosen/mt6762-handoff",&handoff)!=kSuccess ||
        mt6762_handoff_u32("version",&version) || version!=1 || !flag("native-io")) {
        handoff=NULL;printf("MT6762: native peripherals disabled (no versioned handoff)\n");
    } else {
        __atomic_store_n(&ready,1,__ATOMIC_RELEASE);
    }
    lck_mtx_unlock(&mt6762_attach_lock);
}
void mt6762_platform_init(void)
{
    uint32_t hz;
    mt6762_platform_attach();
    if (!mt6762_platform_ready() || initialized) return;
    initialized=1; /* Called only by the BSD initialization thread. */
    if(flag("touch-inherited-probe") && !touch_entry_check()) {
        kprintf("MT6762_TOUCH_ENTRY refused live clock/pad/reset/EINT/controller state\n");return;
    }
    gpio=(uintptr_t)mt6762_map_mmio(0x10005000,0x1000);
    if (!flag("dma-direct") || !flag("i2c-pads-verified") ||
        mt6762_handoff_u32("i2c-parent-index",&parent_index) || parent_index>4 ||
        mt6762_handoff_u32("i2c-parent-hz",&parent_hz)) {
        printf("MT6762: I2C handoff incomplete; power/display may initialize separately\n");return;
    }
    top=(uintptr_t)mt6762_map_mmio(0x10000000,0x1000);
    infra=(uintptr_t)mt6762_map_mmio(0x10001000,0x1000);
    gic=(uintptr_t)mt6762_map_mmio(0xc000000,0x1000);
    if (parent_index) pll=(uintptr_t)mt6762_map_mmio(0x1000c000,0x1000);
    if (!gpio || !top || !infra || !gic || clock_rate(&hz) || hz!=parent_hz) {
        printf("MT6762: I2C clock source readback disagrees with handoff\n");return;
    }
    /* Preserve the selected PLL/parent; enable only the AP I2C and APDMA gates. */
    if (r32(top,0xa0)&0x80) {w32(top,0xa8,0x80);w32(top,4,1u<<24);}
    w32(infra,0x84,1u<<11);w32(infra,0x8c,1u<<18);
    if (!clocks_stable()) {printf("MT6762: I2C clock gates failed readback\n");return;}
    initialize_bus(&buses[0],0);initialize_bus(&buses[1],5);
}
static uintptr_t watchdog;
static int watchdog_matches(void)
{
    return r32(watchdog,0)==0x7d && (r32(watchdog,4)&0xffe0)==0xf000 &&
        r32(watchdog,0x30)==0x3f0036 && r32(watchdog,0x34)==0x3b0034;
}
static void watchdog_worker(void *parameter,wait_result_t wait_result)
{
    (void)parameter;(void)wait_result;
    unsigned count=0;uint64_t previous=0;
    for(;;) {
        uint64_t now,ns,deadline;clock_get_uptime(&now);
        absolutetime_to_nanoseconds(now-previous,&ns);
        if(!watchdog_matches() || (previous && ns>10000000000ULL)) {
            kprintf("MT6762_WATCHDOG stopped: inherited state changed or scheduling gap; attempts=%u\n",count);
            break;
        }
        /* Exact stock ping: never change enable, period, reset/IRQ routing. */
        __asm__ volatile("dsb st":::"memory");
        w32(watchdog,8,0x1971);previous=now;++count;
        if(count==1 || count%30==0)
            kprintf("MT6762_WATCHDOG refresh attempts=%u gap_ms=%llu\n",count,count==1?0:ns/1000000);
        clock_interval_to_deadline(1000,NSEC_PER_MSEC,&deadline);
        assert_wait_deadline((event_t)&watchdog,THREAD_UNINT,deadline);
        thread_block(THREAD_CONTINUE_NULL);
    }
    thread_terminate(current_thread());
}
void mt6762_watchdog_init(void)
{
    thread_t thread;
    if(watchdog || !ready || !flag("watchdog-refresh-owned"))return;
    watchdog=(uintptr_t)mt6762_map_mmio(0x10007000,0x1000);
    if(!watchdog || !watchdog_matches()) {
        kprintf("MT6762_WATCHDOG refused inherited profile\n");return;
    }
    if(kernel_thread_start(watchdog_worker,NULL,&thread)==KERN_SUCCESS)thread_deallocate(thread);
    else kprintf("MT6762_WATCHDOG worker creation failed\n");
}
#else
void mt6762_platform_init(void) {}
void mt6762_platform_attach(void) {}
int mt6762_platform_ready(void) {return 0;}
int mt6762_handoff_u32(const char *n,uint32_t *v) {(void)n;(void)v;return -1;}
int mt6762_handoff_u64(const char *n,uint64_t *v) {(void)n;(void)v;return -1;}
void *mt6762_map_mmio(uint64_t p,size_t n) {(void)p;(void)n;return NULL;}
int mt6762_i2c_transfer(unsigned b,unsigned a,const void *t,size_t nt,void *r,size_t nr)
{(void)b;(void)a;(void)t;(void)nt;(void)r;(void)nr;return -1;}
int mt6762_i2c_ready(unsigned b) {(void)b;return 0;}
int mt6762_gpio_input(unsigned p,unsigned *l) {(void)p;(void)l;return -1;}
#endif
