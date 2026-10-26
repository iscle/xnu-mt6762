#!/usr/bin/env python3
"""Compile actual BSD request/lock code against buffer stubs, without devices."""
from pathlib import Path
import subprocess,tempfile,unittest
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[3]/'bsd/dev/mt6762_msdc_bsd.c'
PRE=r'''
#define _GNU_SOURCE
#include <sys/types.h>
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
#include <string.h>
#include <errno.h>
#define SECTOR 512u
#define MAX_READ (128u*1024u)
#define B_READ 1u
#define minor(d) ((unsigned)(d))
static uint64_t ios_start=100,capacity=2000,ios_count=400;
static int ready=1,locked,msdc_bsd_lock,calls,error_to_return,mapped,completed;
static uint64_t actual_lba;static unsigned actual_blocks;
static int disk_ready(void){return ready;}
static uint64_t disk_capacity(dev_t d){return d==0?capacity:d==1?ios_count:0;}
static void lck_mtx_lock(int*p){(void)p;assert(!locked);locked=1;}
static void lck_mtx_unlock(int*p){(void)p;assert(locked);locked=0;}
static int blocks_read(uint64_t lba,unsigned count,void*out){assert(locked);calls++;actual_lba=lba;actual_blocks=count;
 if(!error_to_return)memset(out,0x69,count*512);return error_to_return;}
struct buffer{size_t count;uint32_t resid,flags;int64_t block;dev_t dev;char*data;int error;};
typedef struct buffer*buf_t;
static size_t buf_count(buf_t b){return b->count;}
static int64_t buf_blkno(buf_t b){return b->block;}
static dev_t buf_device(buf_t b){return b->dev;}
static unsigned buf_flags(buf_t b){return b->flags;}
static void buf_setresid(buf_t b,uint32_t n){b->resid=n;}
static int buf_map(buf_t b,caddr_t*out){*out=b->data;mapped++;return 0;}
static int buf_unmap(buf_t b){(void)b;mapped--;return 0;}
static void buf_seterror(buf_t b,int e){b->error=e;}
static void buf_biodone(buf_t b){(void)b;completed++;}
'''
MAIN=r'''
int main(void){char data[MAX_READ+512];struct buffer b={.count=MAX_READ,.flags=B_READ,.block=0,.dev=1,.data=data};
 memset(data,0xa5,sizeof(data));disk_strategy(&b);assert(!b.error&&!b.resid&&calls==1&&actual_blocks==256&&actual_lba==100&&!locked&&!mapped&&completed==1);
 for(unsigned i=0;i<MAX_READ;i++)assert((unsigned char)data[i]==0x69);
 for(unsigned i=MAX_READ;i<sizeof(data);i++)assert((unsigned char)data[i]==0xa5);
 // Near EOF: one valid sector out of a two-sector buffer; untouched tail and exact residual.
 b=(struct buffer){.count=1024,.flags=B_READ,.block=399,.dev=1,.data=data};memset(data,0xa5,sizeof(data));disk_strategy(&b);
 assert(!b.error&&b.resid==512&&actual_lba==499&&actual_blocks==1&&calls==2);
 for(unsigned i=0;i<512;i++)assert((unsigned char)data[i]==0x69);
 for(unsigned i=512;i<sizeof(data);i++)assert((unsigned char)data[i]==0xa5);
 // Failure is batch-atomic: no partial byte publication and full residual.
 b=(struct buffer){.count=MAX_READ,.flags=B_READ,.block=0,.dev=1,.data=data};error_to_return=EIO;memset(data,0xa5,sizeof(data));disk_strategy(&b);
 assert(b.error==EIO&&b.resid==MAX_READ&&calls==3&&!locked&&!mapped);
 for(unsigned i=0;i<sizeof(data);i++)assert((unsigned char)data[i]==0xa5);
 // Invalid requests and exact EOF never call the transport.
 const struct buffer bad[]={
 {.count=512,.flags=0,.block=0,.dev=1,.data=data},
 {.count=513,.flags=B_READ,.block=0,.dev=1,.data=data},
 {.count=MAX_READ+512,.flags=B_READ,.block=0,.dev=1,.data=data},
 {.count=512,.flags=B_READ,.block=-1,.dev=1,.data=data},
 {.count=512,.flags=B_READ,.block=401,.dev=1,.data=data},
 {.count=512,.flags=B_READ,.block=0,.dev=2,.data=data}};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++){b=bad[i];disk_strategy(&b);assert(b.error&&b.resid==b.count&&calls==3&&!mapped&&!locked);}
 b=(struct buffer){.count=512,.flags=B_READ,.block=400,.dev=1,.data=data};disk_strategy(&b);assert(!b.error&&b.resid==512&&calls==3);
 assert(read_many(1,399,2,data)==EINVAL&&calls==3);
 assert(read_many(1,0,257,data)==EINVAL&&calls==3);
 ready=0;assert(read_many(1,0,1,data)==EINVAL&&calls==3);
 return 0;}
'''

PUB_PRE=r'''
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
#include <errno.h>
#include <string.h>
#define DEVFS_BLOCK 1
#define DEVFS_CHAR 2
#define UID_ROOT 0
#define GID_OPERATOR 5
#define makedev(a,b) (((a)<<8)|(b))
#define printf(...) ((void)0)
static const int block_ops=1,char_ops=2;
static int stage,fail_stage,badds,cadds,bremoves,cremoves,nodes,removed,with_slice=1;
static uint64_t start_value=100,count_value=400;
static int bad_slice;
static int mt6762_handoff_u32(const char *key,uint32_t *out) {
 assert(!strcmp(key,"ios-system-slice"));if(!with_slice)return -1;*out=bad_slice?2:1;return 0;
}
static int mt6762_handoff_u64(const char *key,uint64_t *out) {
 if(!strcmp(key,"ios-system-start-sector"))*out=start_value;
 else {assert(!strcmp(key,"ios-system-sector-count"));*out=count_value;}return 0;
}
static int bdevsw_add(int n,const int *ops) {assert(n==-1&&ops==&block_ops);badds++;return ++stage==fail_stage?-1:4;}
static int cdevsw_add_with_bdev(int n,const int *ops,int b) {assert(n==-1&&ops==&char_ops&&b==4);cadds++;return ++stage==fail_stage?-1:5;}
static void *devfs_make_node(int dev,int type,int uid,int gid,int mode,const char *name) {
 assert(uid==0&&gid==5&&mode==0600);assert(type==DEVFS_BLOCK||type==DEVFS_CHAR);
 assert((dev>>8)==(type==DEVFS_BLOCK?4:5));assert(name&&*name);
 if(++stage==fail_stage)return NULL;nodes++;return (void *)(uintptr_t)nodes;
}
static void devfs_remove(void *node) {unsigned bit=1u<<((unsigned)(uintptr_t)node-1);assert(!(removed&bit));removed|=bit;}
static void bdevsw_remove(int n,const int *ops) {assert(n==4&&ops==&block_ops);bremoves++;}
static void cdevsw_remove(int n,const int *ops) {assert(n==5&&ops==&char_ops);cremoves++;}
static int reader(uint64_t lba,unsigned count,void *out) {(void)lba;(void)count;(void)out;return 0;}
'''
PUB_MAIN=r'''
static void reset(void) {
 capacity=ios_start=ios_count=0;blocks_read=NULL;ready=publishing=0;bmajor=cmajor=-1;
 stage=fail_stage=badds=cadds=bremoves=cremoves=nodes=removed=bad_slice=0;
 with_slice=1;start_value=100;count_value=400;
}
int main(void) {
 for(int fail=1;fail<=6;fail++) {
  reset();fail_stage=fail;assert(mt6762_msdc_publish(2000,reader)==ENXIO);
  assert(!ready&&publishing&&!blocks_read&&!capacity&&!ios_start&&!ios_count&&bmajor==-1&&cmajor==-1);
  assert(badds==1&&cadds==(fail>1));assert(bremoves==(fail>1)&&cremoves==(fail>2));
  assert(nodes==(fail>2?fail-3:0));assert(removed==((1<<nodes)-1));
  int oldstage=stage;assert(mt6762_msdc_publish(2000,reader)==EBUSY&&stage==oldstage);
 }
 for(int slice=0;slice<=1;slice++) {
  reset();with_slice=slice;assert(!mt6762_msdc_publish(2000,reader));
  assert(ready&&publishing&&blocks_read==reader&&capacity==2000&&bmajor==4&&cmajor==5);
  assert(ios_start==(slice?100:0)&&ios_count==(slice?400:0));assert(nodes==(slice?4:2)&&!removed&&!bremoves&&!cremoves);
  int oldstage=stage;assert(mt6762_msdc_publish(2000,reader)==EBUSY&&stage==oldstage);
 }
 reset();assert(mt6762_msdc_publish(0,reader)==EINVAL);assert(mt6762_msdc_publish((uint64_t)UINT32_MAX+1,reader)==EINVAL);
 assert(mt6762_msdc_publish(2000,NULL)==EINVAL);bad_slice=1;assert(mt6762_msdc_publish(2000,reader)==EINVAL);
 bad_slice=0;start_value=2000;assert(mt6762_msdc_publish(2000,reader)==EINVAL);
 start_value=1999;count_value=2;assert(mt6762_msdc_publish(2000,reader)==EINVAL);
 count_value=0;assert(mt6762_msdc_publish(2000,reader)==EINVAL);assert(!stage&&!publishing&&!ready&&!blocks_read);
 return 0;
}
'''

class BSDTests(unittest.TestCase):
 def test_actual_strategy_batch_lock_capacity_atomic_output_residual(self):
  text=SOURCE.read_text();start=text.index('static int read_many(');end=text.index('static int disk_ioctl',start)
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'test.c').write_text(PRE+text[start:end]+MAIN)
   subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True,timeout=10)
 def test_actual_publication_cleanup_all_registration_failure_stages(self):
  text=SOURCE.read_text()
  declarations=text[text.index('static uint64_t capacity;'):text.index('static int disk_ready(void)')]
  publication=text[text.index('int mt6762_msdc_publish('):]
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'test.c').write_text(PUB_PRE+declarations+publication+PUB_MAIN)
   subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True,timeout=10)
if __name__=='__main__':unittest.main()
