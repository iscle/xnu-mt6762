#!/usr/bin/env python3
"""Offline hash-pinned DA2 startup/allocator extent audit; no device interface."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

LOADER_SHA='aef234190ccb8145d2e3b8459741e9adb70f2caa8481aa216c1b25152afaca1f'
DA2_SHA='658ff869c301fadc1a84a9409a55b5b5bdcf01524a1f904aad29a89a07ef2dec'
SPANS=[('arm_startup',0,0xfc,CS_MODE_ARM),('startup_literals',0xfc,0x124,None),
 ('kmain',0xbfc,0xce2,CS_MODE_THUMB),('idle_thread_create',0xb84,0xbac,CS_MODE_THUMB),
 ('thread_allocates_stack',0xe74,0xef0,CS_MODE_THUMB),
 ('thread_stack_top_initialize',0x7e8,0x80a,CS_MODE_THUMB),
 ('heap_size',0xa338,0xa340,CS_MODE_THUMB),('heap_size_literals',0xa340,0xa348,None),
 ('heap_init',0xadd4,0xadf8,CS_MODE_THUMB),('heap_init_literals',0xadf8,0xae00,None),
 ('heap_allocator',0xacc8,0xad7e,CS_MODE_THUMB)]
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--loader',required=True,type=Path)
 p.add_argument('--output',required=True,type=Path);a=p.parse_args();b=a.loader.read_bytes()
 if sha(b)!=LOADER_SHA:p.error('unsupported loader hash')
 assert struct.unpack_from('<I',b,0x68)[0]==50
 o=0x6c+22*0xdc;head=struct.unpack_from('<10H',b,o)
 assert head[1]==0x6765 and head[9]==3
 regions=[]
 for n in range(head[9]):
  offset,length,address,entry_offset,sig=struct.unpack_from('<5I',b,o+20+20*n)
  regions.append(dict(index=n,file_offset=hex(offset),length=hex(length),address=hex(address),
                      start_offset_field=hex(entry_offset),signature_length=hex(sig),
                      sha256=sha(b[offset:offset+length])))
 r=regions[2];offset=int(r['file_offset'],16);length=int(r['length'],16);data=b[offset:offset+length]
 assert sha(data)==DA2_SHA
 def word(off):return struct.unpack_from('<I',data,off)[0]
 base=word(0x100);file_end=word(0x104);bss_start=word(0x11c);bss_end=word(0x120)
 heap_start=word(0xadf8);heap_end=word(0xa344)
 assert (base,file_end,bss_start,bss_end,heap_start,heap_end)==(0x40000000,0x4005108c,0x40051090,0x4005e2a0,0x4005e2a0,0x68000000)
 assert word(0xa340)==heap_start
 spans=[]
 for name,lo,hi,mode in SPANS:
  block=data[lo:hi];item=dict(name=name,start=hex(base+lo),end_exclusive=hex(base+hi),sha256=sha(block))
  if mode is not None:
   instructions=list(Cs(CS_ARCH_ARM,mode).disasm(block,base+lo));assert sum(i.size for i in instructions)==len(block)
   item['instructions']=[dict(va=hex(i.address),instruction=i.mnemonic+' '+i.op_str) for i in instructions]
  else:item['literal_words']=[hex(word(k)) for k in range(lo,hi,4)]
  spans.append(item)
 trace=0x40084000
 result=dict(loader_sha256=LOADER_SHA,entry_index_zero_based=22,hwcode='0x6765',regions=regions,
             ranges=dict(da2_code_and_data=[hex(base),hex(file_end)],
                         da2_with_signature=[hex(base),hex(base+length)],
                         startup_bss_clear=[hex(bss_start),hex(bss_end)],
                         initial_banked_stack_top=hex(word(0x10c)),
                         heap_managed=[hex(heap_start),hex(heap_end)]),
             trace_address=hex(trace),trace_inside_heap=heap_start<=trace<heap_end,
             bounded_original_code=spans,
             findings=['Trace lies outside file and BSS but inside DA2 heap.',
                       'Startup creates idle/bootstrap threads requesting 1MiB stacks via heap allocator.',
                       'Thread initialization zeroes only the top0xac context bytes; no claim entire stack is immediately zeroed.',
                       'DA reconnection may overwrite trace through runtime allocations or stack use; preservation is not proven.'],
             limits=['This is a startup/allocator audit, not a whole-DA write-set proof.',
                     'DA1, preloader DRAM initialization, DA patches/extensions and later I/O buffers are not exhaustively modeled.',
                     'No claim that absence of trace proves the physical payload did not execute.',
                     'No firmware bytes, phone commands or physical writes are produced.'])
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'trace_inside_heap':True,'heap_start':hex(heap_start),'heap_end':hex(heap_end)}))
if __name__=='__main__':main()
