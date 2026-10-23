#ifndef _SYS_MT6762_GAUGE_H_
#define _SYS_MT6762_GAUGE_H_
#ifdef KERNEL
void mt6762_gauge_init(void);
int mt6762_gauge_current_read(int *microamps);
#endif
#endif
