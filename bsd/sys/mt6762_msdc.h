#ifndef _SYS_MT6762_MSDC_H_
#define _SYS_MT6762_MSDC_H_
#include <stdbool.h>
#include <sys/types.h>
#ifdef KERNEL
void mt6762_storage_init(void);
/* Only publish after controller/card admission. Callback returns BSD errno,
 * reads count*512 bytes (count1..256), and must not touch output on failure. */
int mt6762_msdc_publish(uint64_t sectors, int (*read_blocks)(uint64_t,unsigned,void *));
bool mt6762_storage_dev(dev_t dev); /* Block-device namespace only. */
#endif
#endif
