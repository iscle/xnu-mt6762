#!/usr/bin/env python3
"""Bounded offline capture-pattern/test-call audit; no attribution from pattern."""
import argparse,hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
PLSHA='7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674'
LOADERSHA='aef234190ccb8145d2e3b8459741e9adb70f2caa8481aa216c1b25152afaca1f'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['preloader','loader','capture2','capture4','output']:p.add_argument('--'+name,required=True,type=Path)
 a=p.parse_args();pl=a.preloader.read_bytes();loader=a.loader.read_bytes()
 if sha(pl)!=PLSHA or sha(loader)!=LOADERSHA:p.error('artifact digest mismatch')
 da1=loader[0x719904:0x719904+0x39f98];pattern=a.capture2.read_bytes()
 assert len(pattern)==256 and sha(pattern)=='5a872f002e1d83f6accf9aef6810f965b3e14213835b1881484d9c2afd1bd6c7'
 block=bytes([255])*30+bytes([251])*2;assert pattern==block*8
 ranges=[]
 for name,start,end in [('rank0_test_arguments',0x21e37e,0x21e38a),('rank1_dynamic_test_arguments',0x21e3b6,0x21e3d8)]:
  raw=pl[start-0x200710:end-0x200710];ins=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(raw,start))
  assert sum(i.size for i in ins)==len(raw)
  ranges.append({'name':name,'start':hex(start),'end_exclusive':hex(end),'sha256':sha(raw),
                 'instructions':[{'va':hex(i.address),'instruction':i.mnemonic+' '+i.op_str} for i in ins]})
 observed=json.loads(a.capture4.read_text());trace=observed['trace']
 assert trace['identity']=='b06becb67a750182c3a95d3c523881e4673793995b11fe7e7ee78d98cbc273b4'
 assert (trace['phase'],trace['previous_phase'],trace['detail'])==(254,4,261)
 result={'preloader_sha256':PLSHA,'loader_sha256':LOADERSHA,'da1_sha256':sha(da1),
  'capture2_pattern':{'sha256':sha(pattern),'length':256,'period_bytes':32,'period':'30 bytes0xff then2 bytes0xfb','writer_identified':False},
  'bounded_stock_calls':ranges,'rank0_test_requested_range':['0x48000000','0x48002000'],
  'rank1_test':'base computed via0x216f8c plus0x40000000; requested size0x2000; actual remapping not established here',
  'static_exact_pattern_word_search':{'preloader_contains_fffffbfb':bytes.fromhex('fffffbfb') in pl,
    'da1_contains_fffffbfb':bytes.fromhex('fffffbfb') in da1,
    'limitation':'No match does not exclude generated patterns or hardware test engines.'},
  'capture4_positive':{'report_sha256':sha(a.capture4.read_bytes()),'trace_sha256':observed['trace_sha256'],
    'phase':254,'previous_phase':4,'detail':261,'midr':hex(trace['midr']),'fdt':hex(trace['fdt']),
    'original_el':trace['original_el'],'frequency':trace['frequency'],
    'reservation_runtime_verified':observed['reservation_runtime_verified'],
    'interpretation':'Build-bound loader trace survived this trial and reached parser refusal; no proof XNU executed or universal retention.'},
  'disposition':'Investigation bounded and closed after positive capture4. No alternate trace address or memory-write change proposed.'}
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'capture2_writer_identified':False,'capture4_loader_execution':True,'xnu_execution_proven':False}))
if __name__=='__main__':main()
