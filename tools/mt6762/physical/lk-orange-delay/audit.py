#!/usr/bin/env python3
"""Read-only bounded provenance and exact Thumb disassembly."""
import argparse,hashlib,json,struct,zlib
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from patch import SHA,BASE,patch,digest

def main():
 p=argparse.ArgumentParser();p.add_argument('--stock',type=Path,required=True);p.add_argument('--bsp',type=Path,required=True);p.add_argument('--captured',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 b=a.stock.read_bytes();patch(b)
 c=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
 regions={}
 for name,lo,hi in [('orange',0x48037964,0x480379a6),('dispatch',0x48037a84,0x48037ac0),('delay_ms',0x48042a38,0x48042a90)]:
  regions[name]=[{'address':hex(i.address),'bytes':i.bytes.hex(),'instruction':i.mnemonic+' '+i.op_str} for i in c.disasm(b[lo-BASE:hi-BASE],lo)]
 sources={}
 paths=['lk/platform/common/boot/vboot_state.c','lk/platform/common/include/vboot_state.h','preloader/platform/mt6765/src/core/main.c','preloader/platform/mt6765/src/core/partition.c','preloader/platform/common/partition/part_common.c']
 for r in paths:
  q=a.bsp/'vendor/mediatek/proprietary/bootable/bootloader'/r;sources[str(q)]={'sha256':digest(q.read_bytes())}
 g=(a.captured/'gpt-current.bin').read_bytes();h=bytearray(g[512:1024]);assert h[:8]==b'EFI PART'
 hs=struct.unpack_from('<I',h,12)[0];crc=struct.unpack_from('<I',h,16)[0];struct.pack_into('<I',h,16,0);assert zlib.crc32(h[:hs])==crc
 lba,n,s=struct.unpack_from('<QII',g,512+72);entries=g[lba*512:lba*512+n*s];assert zlib.crc32(entries)==struct.unpack_from('<I',g,512+88)[0]
 slots={}
 for i in range(n):
  e=entries[i*s:(i+1)*s];name=e[56:].decode('utf-16le').split('\0')[0]
  if name in ['lk','lk2']:
   first,last,attr=struct.unpack_from('<QQQ',e,32);q=a.captured/(name+'-current.bin');assert digest(q.read_bytes())==SHA
   slots[name]={'byte_address':hex(first*512),'bytes':(last-first+1)*512,'gpt_attributes':hex(attr),'captured_sha256':digest(q.read_bytes())}
 assert set(slots)=={'lk','lk2'}
 out={'authority':'Exact stock LK instructions and read-only captured GPT/slots; BSP loading/auth source is corroboration, not proof of exact fused device policy','stock_sha256':digest(b),'sources':sources,'ranges':regions,'gpt_crc_verified':True,'gpt_sha256':digest(g),'installed_slots':slots,'selection':'Both attribute words zero. BSP bldr_load_part_lk therefore selects primary lk; exact runtime selector not replayed. No automatic fallback claim.','auth_boundary':'BSP part_load gates sec_img_auth_init/sec_img_auth through get_vfy_policy; exact running preloader/fuse policy unresolved. No signatures or hash metadata regenerated. BootROM DA acceptance does not prove normal LK acceptance.'}
 a.output.write_text(json.dumps(out,indent=2)+'\n');print('PASS: pinned LK, captured slots, both GPT CRCs, bounded disassembly')
if __name__=='__main__':main()
