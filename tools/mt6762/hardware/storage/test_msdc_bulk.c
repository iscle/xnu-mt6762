/* SPDX-License-Identifier: MIT: actual bounded CMD23/CMD18 engine, no MMIO. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../../../../bsd/dev/mt6762_msdc_protocol.h"
enum {NONE,CMD23_BAD,CMD18_BAD,CRC_LATE,SHORT,NO_DONE,ACK_STUCK,POST_BAD,OWNER_LOST,NEVER_READY,BAD_BLOCK,DONE_ERROR};
struct lab {unsigned opcode,block,predefined,have,total,active,commands,ops[16],fault,mode;uint32_t irq,arg;uint64_t time;};
static int admit(void *p){struct lab*f=p;return f->fault==OWNER_LOST && f->opcode==18 && f->have==f->total;}
static uint32_t read32(void*p,uint32_t r){struct lab*f=p;
 switch(r){case 0:return 0x89;case 0x30:return 0x20000;case 0x670:return 4;
 case 0x10:case 0x3c:case 0x9c:case 0x204:case 0x23c:return 0;
 case 0x50:return f->block+(f->fault==BAD_BLOCK);
 case 0xc:if(f->fault==CRC_LATE && f->have>=f->total-64 && f->active)f->irq|=0x8000;return f->irq;
 case 0x40:return f->fault==POST_BAD && f->opcode==13 && f->total?0xb00:0x900;
 case 0x14:
  if(!f->active || f->fault==NEVER_READY)return 0;
  if(f->fault==SHORT && f->have>=f->total-256)return 0;
  return f->total-f->have>128?128:f->total-f->have;
 case 0x1c:{assert(f->active && f->have+4<=f->total);uint32_t v=0;
  for(unsigned j=0;j<4;j++)v|=(uint32_t)((f->have++*7+3)&255)<<(8*j);
  if(f->have==f->total){f->active=0;if(f->fault!=NO_DONE)f->irq|=0x1000;if(f->fault==DONE_ERROR)f->irq|=0x8000;}
  return v;}
 default:assert(!"unexpected register");return 0;
 }}
static void write32(void*p,uint32_t r,uint32_t v){struct lab*f=p;
 switch(r){case 0x50:assert(v>=2 && v<=256);f->block=v;break;
 case 0x38:f->arg=v;break;
 case 0x34:
  assert(v==0x8d || v==0x97 || v==0x02001092);f->opcode=v&63;
  assert(f->commands<16);f->ops[f->commands++]=f->opcode;f->irq=0x100;
  if(f->opcode==23){assert(f->arg>=2 && f->arg<=256);f->predefined=f->arg;if(f->fault==CMD23_BAD)f->irq|=0x400;}
  if(f->opcode==18){assert(f->predefined==f->block);f->predefined=0;f->have=0;f->total=f->block*512;f->active=1;if(f->fault==CMD18_BAD)f->irq|=0x400;}
  break;
 case 0xc:assert(!(v&~0x1100));if(!(f->fault==ACK_STUCK && v==0x1000))f->irq&=~v;break;
 default:assert(!"forbidden reset/stop/DMA/write command");}}
static uint64_t time_us(void*p){struct lab*f=p;return f->mode==2?f->time--:f->time;}
static void delay_us(void*p,uint32_t us){struct lab*f=p;if(!f->mode)f->time+=us;}
static struct mt6762_msdc engine(struct lab*f){struct mt6762_msdc s={0};
 s.io=(struct mt6762_msdc_io){f,admit,read32,write32,time_us,delay_us};
 s.config=(struct mt6762_msdc_config){1024,1,0x89,0x20000,8,200000000};s.initialized=1;return s;}
int main(void){const size_t maximum=256*512;uint8_t*out=malloc(maximum+32),*scratch=malloc(maximum);assert(out&&scratch);
 for(unsigned n=2;n<=256;n=n==2?32:256){struct lab f={0};struct mt6762_msdc s=engine(&f);memset(out,0xa5,maximum+32);
  assert(mt6762_msdc_read_blocks(&s,1024-n,n,out+16,scratch,maximum)==0);
  assert(f.commands==4 && f.ops[0]==13 && f.ops[1]==23 && f.ops[2]==18 && f.ops[3]==13);
  assert(f.have==n*512 && !f.active && !f.predefined && !f.irq && !s.faulted);
  for(unsigned i=0;i<n*512;i++)assert(out[16+i]==(uint8_t)(i*7+3));
  for(unsigned i=0;i<16;i++)assert(out[i]==0xa5 && out[16+n*512+i]==0xa5);
  if(n==256)break;
 }
 for(unsigned fault=CMD23_BAD;fault<=DONE_ERROR;fault++)for(unsigned mode=0;mode<3;mode++){
  struct lab f={.fault=fault,.mode=mode,.time=100};struct mt6762_msdc s=engine(&f);memset(out,0xa5,maximum+32);
  assert(mt6762_msdc_read_blocks(&s,0,32,out+16,scratch,maximum)<0 && s.faulted);
  for(unsigned i=0;i<maximum+32;i++)assert(out[i]==0xa5);
  unsigned before=f.commands;assert(mt6762_msdc_read_blocks(&s,0,32,out+16,scratch,maximum)==MT6762_MSDC_FAULTED);assert(f.commands==before);
 }
 {struct lab f={0};struct mt6762_msdc s=engine(&f);
  const unsigned bad[]={0,1,257,UINT32_MAX};for(unsigned i=0;i<4;i++)assert(mt6762_msdc_read_blocks(&s,0,bad[i],out,scratch,maximum)==MT6762_MSDC_ARGUMENT);
  assert(mt6762_msdc_read_blocks(&s,1023,2,out,scratch,maximum)==MT6762_MSDC_ARGUMENT);
  assert(mt6762_msdc_read_blocks(&s,UINT64_MAX,2,out,scratch,maximum)==MT6762_MSDC_ARGUMENT);
  assert(mt6762_msdc_read_blocks(&s,0,2,out,scratch,1023)==MT6762_MSDC_ARGUMENT);
  assert(mt6762_msdc_read_blocks(&s,0,2,out,out+512,maximum)==MT6762_MSDC_ARGUMENT);
  assert(!f.commands && !s.faulted);
 }
 free(out);free(scratch);puts("PASS: actual CMD13/CMD23/CMD18/CMD13 bounded 2/32/256-sector PIO, atomic output, capacity, terminal errors and clock bounds");return 0;}
