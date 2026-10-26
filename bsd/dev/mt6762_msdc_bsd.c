/* Read-only BSD adapter for the owned MT6762 eMMC PIO transport.
 * User faults happen outside the controller lock; no storage writes exist. */
#include <kern/locks.h>
#include <libkern/libkern.h>
#include <miscfs/devfs/devfs.h>
#include <sys/buf.h>
#include <sys/conf.h>
#include <sys/disk.h>
#include <sys/errno.h>
#include <sys/mt6762_msdc.h>
#include <sys/mt6762_platform.h>
#include <sys/systm.h>
#include <sys/uio.h>

#define SECTOR 512u
#define MAX_READ (128u * 1024u) /* APFS_DATA_MAX, including shared-cache reads. */
static LCK_GRP_DECLARE(msdc_bsd_group,"mt6762-msdc-bsd");
static LCK_MTX_DECLARE(msdc_bsd_lock,&msdc_bsd_group);
static uint64_t capacity;
static uint64_t ios_start,ios_count;
static int (*sector_read)(uint64_t,void *);
static int ready,publishing,bmajor=-1,cmajor=-1;
static int disk_ready(void)
{return __atomic_load_n(&ready,__ATOMIC_ACQUIRE);}

bool mt6762_storage_dev(dev_t dev)
{return disk_ready() && major(dev)==bmajor && (minor(dev)==0 || (minor(dev)==1 && ios_count));}

static uint64_t disk_capacity(dev_t dev)
{return minor(dev)==0?capacity:(minor(dev)==1?ios_count:0);}

static int disk_open(dev_t dev,int flags,__unused int type,__unused proc_t p)
{
    if(!disk_ready() || !disk_capacity(dev))return ENXIO;
    return flags&FWRITE?EROFS:0;
}
static int disk_close(__unused dev_t d,__unused int f,__unused int t,__unused proc_t p)
{return 0;}

static int read_one(dev_t dev,uint64_t sector,void *out)
{
    int error;
    if(!disk_ready() || sector>=disk_capacity(dev))return EINVAL;
    if(minor(dev)==1)sector+=ios_start; /* Full extent checked before publication. */
    lck_mtx_lock(&msdc_bsd_lock);
    error=sector_read(sector,out);
    lck_mtx_unlock(&msdc_bsd_lock);
    return error;
}

static void disk_strategy(buf_t bp)
{
    size_t requested=buf_count(bp),length=requested,done=0;
    int error=0;
    caddr_t data=NULL;
    int64_t block=buf_blkno(bp);
    dev_t dev=buf_device(bp);
    uint64_t count=disk_capacity(dev);
    buf_setresid(bp,(uint32_t)requested);
    if(!disk_ready() || !count) {error=ENXIO;goto finished;}
    if(!(buf_flags(bp)&B_READ)) {error=EROFS;goto finished;}
    if(block<0 || (requested%SECTOR) || requested>MAX_READ) {error=EINVAL;goto finished;}
    if((uint64_t)block>=count) {
        if((uint64_t)block>count)error=EINVAL;
        goto finished;
    }
    uint64_t remaining=(count-(uint64_t)block)*SECTOR;
    if(length>remaining)length=(size_t)remaining;
    if(!length)goto finished;
    error=buf_map(bp,&data);
    if(error)goto finished;
    while(done<length) {
        error=read_one(dev,(uint64_t)block+done/SECTOR,data+done);
        if(error)break;
        done+=SECTOR;
    }
    {
        int unmap_error=buf_unmap(bp);
        if(!error)error=unmap_error;
    }
    buf_setresid(bp,(uint32_t)(requested-done));
finished:
    if(error)buf_seterror(bp,error);
    buf_biodone(bp);
}

static int disk_ioctl(dev_t dev,u_long command,caddr_t data,__unused int flags,__unused proc_t p)
{
    if(!disk_ready() || !disk_capacity(dev))return ENXIO;
    switch(command) {
    case DKIOCGETBLOCKSIZE: *(uint32_t *)data=SECTOR;return 0;
    case DKIOCSETBLOCKSIZE: return *(uint32_t *)data==SECTOR?0:EINVAL;
    case DKIOCGETBLOCKCOUNT: *(uint64_t *)data=disk_capacity(dev);return 0;
    case DKIOCISWRITABLE: *(uint32_t *)data=0;return 0;
    case DKIOCGETMAXBLOCKCOUNTREAD: *(uint64_t *)data=MAX_READ/SECTOR;return 0;
    default:return ENOTTY;
    }
}
static int disk_size(dev_t dev) {return disk_ready() && disk_capacity(dev)?(int)SECTOR:-1;}

static int disk_read(dev_t dev,struct uio *uio,__unused int flags)
{
    uint8_t scratch[SECTOR];
    if(!disk_ready() || !disk_capacity(dev))return ENXIO;
    if(uio_offset(uio)<0 || uio_resid(uio)<0)return EINVAL;
    while(uio_resid(uio)>0) {
        uint64_t offset=(uint64_t)uio_offset(uio);
        if(offset>=disk_capacity(dev)*SECTOR)return 0;
        unsigned within=(unsigned)(offset%SECTOR),count=SECTOR-within;
        if((uint64_t)uio_resid(uio)<count)count=(unsigned)uio_resid(uio);
        int error=read_one(dev,offset/SECTOR,scratch);
        if(error)return error;
        /* Copyout may fault and recursively read a filesystem backed by this
         * device. The transport mutex is already released. */
        error=uiomove((caddr_t)scratch+within,count,uio);
        if(error)return error;
    }
    return 0;
}
static const struct bdevsw block_ops={
    .d_open=disk_open,.d_close=disk_close,.d_strategy=disk_strategy,
    .d_ioctl=disk_ioctl,.d_dump=eno_dump,.d_psize=disk_size,.d_type=D_DISK
};
static const struct cdevsw char_ops={
    .d_open=disk_open,.d_close=disk_close,.d_read=disk_read,.d_write=eno_rdwrt,
    .d_ioctl=disk_ioctl,.d_stop=eno_stop,.d_reset=eno_reset,.d_ttys=NULL,
    .d_select=eno_select,.d_mmap=eno_mmap,.d_strategy=eno_strat,
    .d_reserved_1=eno_getc,.d_reserved_2=eno_putc,.d_type=D_DISK
};

int mt6762_msdc_publish(uint64_t sectors,int (*read_sector)(uint64_t,void *))
{
    void *block_node=NULL,*char_node=NULL,*ios_block=NULL,*ios_char=NULL;
    /* EXT_CSD SEC_COUNT and sector-addressed MMC commands are32-bit. */
    if(!sectors || sectors>UINT32_MAX || !read_sector)return EINVAL;
    uint32_t slice=0;
    uint64_t start=0,count=0;
    if(!mt6762_handoff_u32("ios-system-slice",&slice)) {
        if(slice!=1 || mt6762_handoff_u64("ios-system-start-sector",&start) ||
           mt6762_handoff_u64("ios-system-sector-count",&count) ||
           !count || start>=sectors || count>sectors-start)return EINVAL;
    }
    /* One publication attempt; only a release-published ready disk may be
     * accessed by later CPUs. Registration failure never exposes callbacks. */
    if(__atomic_exchange_n(&publishing,1,__ATOMIC_ACQ_REL))return EBUSY;
    capacity=sectors;sector_read=read_sector;ios_start=start;ios_count=count;
    bmajor=bdevsw_add(-1,&block_ops);
    if(bmajor<0)goto failed;
    cmajor=cdevsw_add_with_bdev(-1,&char_ops,bmajor);
    if(cmajor<0)goto failed;
    block_node=devfs_make_node(makedev(bmajor,0),DEVFS_BLOCK,UID_ROOT,GID_OPERATOR,0600,"mtkemmc0");
    if(!block_node)goto failed;
    char_node=devfs_make_node(makedev(cmajor,0),DEVFS_CHAR,UID_ROOT,GID_OPERATOR,0600,"rmtkemmc0");
    if(!char_node)goto failed;
    if(ios_count) {
        ios_block=devfs_make_node(makedev(bmajor,1),DEVFS_BLOCK,UID_ROOT,GID_OPERATOR,0600,"mtkios0");
        if(!ios_block)goto failed;
        ios_char=devfs_make_node(makedev(cmajor,1),DEVFS_CHAR,UID_ROOT,GID_OPERATOR,0600,"rmtkios0");
        if(!ios_char)goto failed;
    }
    __atomic_store_n(&ready,1,__ATOMIC_RELEASE);
    printf("MT6762 MSDC: read-only /dev/mtkemmc0, %llu sectors\n",capacity);
    if(ios_count)printf("MT6762 MSDC: read-only /dev/mtkios0, start %llu, %llu sectors\n",ios_start,ios_count);
    return 0;
failed:
    if(ios_char)devfs_remove(ios_char);
    if(ios_block)devfs_remove(ios_block);
    if(char_node)devfs_remove(char_node);
    if(block_node)devfs_remove(block_node);
    if(cmajor>=0)cdevsw_remove(cmajor,&char_ops);
    if(bmajor>=0)bdevsw_remove(bmajor,&block_ops);
    cmajor=bmajor=-1;capacity=ios_start=ios_count=0;sector_read=NULL;
    return ENXIO;
}
