#!/usr/bin/env python3
"""Offline exact-stock SSPM AP feedback audit; never opens a physical device.

Requires installed capstone, pyelftools and unicorn. Executes only bounded
original AP decoder/notification routines, with explicit OS callback models.
No SSPM firmware, PLL, regulator or real mailbox execution is represented.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC

BASE = 0xffffff8008080000
IMAGE_SHA = '82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
ELF_SHA = '643474799f7c300f2d3c7f5130f697ee359929f13db0750f4dd7b9d648af14fc'
SPANS = {
 'parse_time_log_content': (0xffffff800867a610, 0xffffff800867a69c),
 'parse_log_content': (0xffffff800867a69c, 0xffffff800867a72c),
 'Ripi_cpu_dvfs_thread': (0xffffff800867a72c, 0xffffff800867ac10),
 'cpuhvfs_get_cur_dvfs_freq_idx': (0xffffff800867b230, 0xffffff800867b268),
 'cpuhvfs_get_cur_volt': (0xffffff800867b2c0, 0xffffff800867b304),
 'cpuhvfs_get_volt': (0xffffff800867b304, 0xffffff800867b33c),
 'cpuhvfs_set_cluster_load_freq': (0xffffff800867b4f8, 0xffffff800867b5dc),
 'sspm_ipi_recv_wait': (0xffffff800880a40c, 0xffffff800880a49c),
 'ipi_isr_cb': (0xffffff800880a104, 0xffffff800880a2d8),
 'sspm_mbox_irq_handler': (0xffffff8008809b54, 0xffffff8008809bdc),
}
SOURCES = [
 'kernel-4.14/drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c',
 'kernel-4.14/drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.h',
 'kernel-4.14/drivers/misc/mediatek/sspm/v1/sspm_ipi_mbox.c',
]

def sha(data): return hashlib.sha256(data).hexdigest()

def execute_checks(image):
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = set()
    def map_page(addr):
        page = addr & ~0xfff
        if page in pages: return
        u.mem_map(page, 4096); pages.add(page)
        off = page - BASE
        if 0 <= off < len(image): u.mem_write(page, image[off:off+4096])
    for lo, hi in SPANS.values():
        for page in range(lo & ~0xfff, (hi+4095)&~4095, 4096): map_page(page)
    for page in [0xffffff80099cb000,0xffffff80099cc000,0xffffff8009a81000]: map_page(page)
    hooks = {}
    # No original ftrace, scheduling, locks, completion or MMIO helper executes.
    hook_names = {
       0xffffff800809ef9c:'ftrace_noop',
       0xffffff8008f2e1d0:'wait_for_completion_model',
       0xffffff800810cc70:'try_wait_for_completion_model',
       0xffffff8008f32768:'spin_trylock_model',
       0xffffff8008f329d8:'spin_unlock_model',
       0xffffff80088094a4:'memcpy_from_sspm_model',
       0xffffff800810cbac:'complete_model',
    }
    for addr in hook_names: map_page(addr)
    for page in range(0x60000000,0x60010000,4096): map_page(page)
    stop=0x6000f000
    def dispatch(uc, addr, size, _):
        if addr in hooks:
            result = hooks[addr]()
            if result is not None: uc.reg_write(UC_ARM64_REG_X0,result)
            uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_X30))
        elif addr in hook_names:
            if addr != 0xffffff800809ef9c:
                raise AssertionError('unconfigured callback '+hook_names[addr])
            uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_X30))
    u.hook_add(UC_HOOK_CODE,dispatch)
    def run(addr,*args):
        u.reg_write(UC_ARM64_REG_SP,0x6000e000)
        u.reg_write(UC_ARM64_REG_X30,stop)
        for reg,arg in zip([UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2],args): u.reg_write(reg,arg)
        u.emu_start(addr,stop,count=10000)
        assert u.reg_read(UC_ARM64_REG_PC)==stop, 'bounded execution did not return'
        return u.reg_read(UC_ARM64_REG_X0)
    def put(addr,fmt,*values): u.mem_write(addr,struct.pack(fmt,*values))
    results=[]
    # Exercise every bit of a cluster word: only bits4..15 affect AP decoding.
    raw=[0x0000d520,0x00003790,0x0000bf40]
    expected=tuple(v for word in raw for v in ((word>>12)&15,(word>>4)&15,(word>>8)&15))
    for flip in [None]+list(range(32)):
        words=[w ^ ((1<<flip) if flip is not None else 0) for w in raw]
        put(0x60000000,'<5I',0x89abcdef,0x12345678,*words)
        run(SPANS['parse_time_log_content'][0],0x89abcdef,0x12345678,0)
        run(SPANS['parse_log_content'][0],0x60000000,0)
        actual=struct.unpack('<Q9I',bytes(u.mem_read(0xffffff80099cb828,44)))
        wanted=tuple(v for w in words for v in ((w>>12)&15,(w>>4)&15,(w>>8)&15))
        assert actual==(0x1234567889abcdef,*wanted)
        if flip is not None and not 4<=flip<=15: assert wanted==expected
    results.append({'case':'original_decoder_all_32_bit_positions','passed':True,'vectors':33,
                    'timestamp':'0x1234567889abcdef','decoded_fields':['opp[15:12]','limit[7:4]','base[11:8]'],
                    'ignored_bits':[0,1,2,3]+list(range(16,32))})
    # Shared current-index getter returns the raw word; it checks no epoch.
    put(0xffffff80099cc008,'<Q',0x60002000)
    for domain in range(3):
        put(0x60002354+4*domain,'<I',0x12345670+domain)
        assert run(SPANS['cpuhvfs_get_cur_dvfs_freq_idx'][0],domain)==0x12345670+domain
    results.append({'case':'original_current_index_raw_snapshot','passed':True,'vectors':3})
    # Receive-wait coalesces completions when the registered action has a lock.
    put(0xffffff8009a812e8,'<B',1)
    put(0xffffff8009a812f0,'<Q',0x60001000)
    put(0x60001010,'<Q',0x60002000)
    for locked in [False,True]:
        put(0x60002010,'<Q',0x60004000 if locked else 0)
        waits=[]; drains=[]
        hooks[0xffffff8008f2e1d0]=lambda: waits.append('wait')
        def drain():
            drains.append(1)
            return int(len(drains)<3)
        hooks[0xffffff800810cc70]=drain
        assert run(SPANS['sspm_ipi_recv_wait'][0],1)==0
        assert len(waits)==1 and len(drains)==(3 if locked else 0)
        results.append({'case':'original_wait_'+('coalesces' if locked else 'without_lock'),
                        'passed':True,'wait_calls':len(waits),'try_wait_calls':len(drains)})
    # Exact notification ISR drops a busy action without copy or completion.
    put(0xffffff8009a81378,'<Q',0x60005000)
    put(0x60005008,'<I',0x01000101) # mailbox2: mode1, pin1..1
    put(0x60001018,'<I',0x2081a)   # exact CPU receive descriptor, 4words slot3
    put(0x60002000,'<Q',0x60006000)
    put(0x60002010,'<Q',0x60004000)
    payload=bytes(range(16)); u.mem_write(0x6000700c,payload)
    for acquired in [False,True]:
        calls=[]; u.mem_write(0x60006000,b'\xff'*16)
        hooks[0xffffff8008f32768]=lambda: int(acquired)
        hooks[0xffffff8008f329d8]=lambda: calls.append('unlock')
        hooks[0xffffff800810cbac]=lambda: calls.append('complete')
        def copy():
            dst=u.reg_read(UC_ARM64_REG_X0); src=u.reg_read(UC_ARM64_REG_X1); length=u.reg_read(UC_ARM64_REG_X2)
            assert (dst,src,length)==(0x60006000,0x6000700c,16)
            u.mem_write(dst,bytes(u.mem_read(src,length))); calls.append('copy')
        hooks[0xffffff80088094a4]=copy
        assert run(SPANS['ipi_isr_cb'][0],2,0x60007000,1)==1
        assert calls==(['copy','unlock','complete'] if acquired else [])
        assert bytes(u.mem_read(0x60006000,16))==(payload if acquired else b'\xff'*16)
        results.append({'case':'original_notification_'+('copies' if acquired else 'drops_busy_lock'),
                        'passed':True,'callback_order':calls})
    return {'cases':results,'modeled_callbacks':{hex(k):v for k,v in hook_names.items()},
            'scope':'Original AP instructions only; modeled RAM, ftrace/OS callbacks; no SSPM producer or hardware.'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True,type=Path); p.add_argument('--elf',required=True,type=Path)
    p.add_argument('--bsp',required=True,type=Path); p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(); image=a.image.read_bytes()
    if sha(image)!=IMAGE_SHA or sha(a.elf.read_bytes())!=ELF_SHA: p.error('exact stock hashes required')
    with a.elf.open('rb') as f:
        symbols={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols()}
    assert all(symbols[name]==span[0] for name,span in SPANS.items())
    md=Cs(CS_ARCH_ARM64,CS_MODE_ARM); spans=[]; disassembly=[]
    for name,(lo,hi) in SPANS.items():
        data=image[lo-BASE:hi-BASE]
        spans.append({'name':name,'start':hex(lo),'end_exclusive':hex(hi),'sha256':sha(data)})
        disassembly.append('\n'+name)
        disassembly.extend(f'{i.address:016x} {i.mnemonic} {i.op_str}' for i in md.disasm(data,lo))
    sources=[{'path':s,'sha256':sha((a.bsp/s).read_bytes())} for s in SOURCES]
    result={'image_sha256':IMAGE_SHA,'elf_sha256':ELF_SHA,'image_va_base':hex(BASE),
            'spans':spans,'bsp_references':sources,'execution':execute_checks(image),
            'limits':['No active SSPM firmware producer was analyzed or executed.',
                      'No physical handoff, mailbox observation, voltage or transition measurement.',
                      'AP decoder evidence does not assign undocumented producer semantics to ignored bits.']}
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'feedback-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
    (a.output/'stock-feedback-disassembly.txt').write_text('\n'.join(disassembly)+'\n')
    print(json.dumps({'cases':len(result['execution']['cases']),'passed':True,'output':str(a.output)}))
if __name__=='__main__': main()
