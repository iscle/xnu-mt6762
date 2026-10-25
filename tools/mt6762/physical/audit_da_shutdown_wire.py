#!/usr/bin/env python3
"""Execute exact DA packet framing + shutdown handler with fake raw USB only.

No device libraries, connection, reset, filesystem writes on phone or payload
execution. Tests stop at the reset callback entry or final shutdown loop.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_PC
from audit_reset_routing import da_cpu,ret,disassemble,LOADER_SHA,DA_SHA

PATCHED_SHA='04a293ab057fed8278e12cbde385f2ad732aebcd9d0878fe16691212c8cdca84'
SPANS=[('shutdown_handler',0x400054ac,0x4000566c),
       ('command_dispatch',0x40006cc4,0x40006e10),
       ('receive_and_transmit',0x40006e3c,0x40006f1c),
       ('timed_transport_wrappers',0x4000a7c0,0x4000a838),
       ('callback_table',0x4004f4e0,0x4004f510)]

def digest(b):return hashlib.sha256(b).hexdigest()
def replay(blob,payload_length,stack_pattern,enablewdt=0):
    u=da_cpu(blob)
    # Actual dispatcher supplies this original table. Replace only its lower
    # raw-USB read/write targets, not the framed wrappers or capacity check.
    u.reg_write(UC_ARM_REG_R0,0x4004f4e0)
    u.mem_write(0x4004f4f8,struct.pack('<II',0x60000201,0x60000205))
    u.mem_write(0x6000e000,bytes([stack_pattern])*0x1000)
    fields=[1,enablewdt,0,1,0,0,0,0]
    payload=struct.pack('<8I',*fields)[:payload_length]
    stream=bytearray(struct.pack('<III',0xfeeeeeef,1,payload_length)+payload)
    raw_reads=[];raw_writes=[];events=[];callbacks=[];receive_result=[];destination=[];terminal=[]
    def code(cpu,address,size,opaque):
        if address in (0x40003c60,0x4000c10c):ret(cpu,3 if address==0x40003c60 else 0)
        elif address in (0x4000abb0,0x4000f20c,0x4000c11a):ret(cpu,0)
        elif address==0x60000200:
            dest=cpu.reg_read(UC_ARM_REG_R0);n=cpu.reg_read(UC_ARM_REG_R1)
            assert 0<n<=len(stream),(n,len(stream))
            cpu.mem_write(dest,bytes(stream[:n]));del stream[:n];raw_reads.append(n);ret(cpu,0)
        elif address==0x60000204:
            src=cpu.reg_read(UC_ARM_REG_R0);n=cpu.reg_read(UC_ARM_REG_R1)
            raw_writes.append(bytes(cpu.mem_read(src,n)).hex());events.append('raw_usb_write');ret(cpu,0)
        elif address==0x400054ea:
            destination.append((cpu.reg_read(UC_ARM_REG_R0),bytes(cpu.mem_read(cpu.reg_read(UC_ARM_REG_R0),32))))
        elif address==0x400054ec:
            receive_result.append(cpu.reg_read(UC_ARM_REG_R0));events.append('receive_return')
        elif address==0x4000e9a8:ret(cpu,1)
        elif address==0x4000e930:callbacks.append('usb_disconnect');events.append('usb_disconnect');ret(cpu,0)
        elif address==0x40017544:callbacks.append('rtc_reset_time');events.append('rtc_reset_time');ret(cpu,0)
        elif address==0x40005540:events.append('flags_validation')
        elif address==0x40017450:
            callbacks.append({'watchdog_reset_args':[cpu.reg_read(UC_ARM_REG_R0),cpu.reg_read(UC_ARM_REG_R1)]})
            terminal.append('watchdog_callback');cpu.emu_stop()
        elif address==0x400055fc:terminal.append('shutdown_loop');cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,code);u.emu_start(0x400054ad,0,count=4000)
    assert len(destination)==len(receive_result)==len(terminal)==1
    addr,before=destination[0];after=bytes(u.mem_read(addr,32))
    assert raw_writes==[struct.pack('<III',0xfeeeeeef,1,4).hex(),'00000000']
    assert events.index('flags_validation')>max(i for i,e in enumerate(events) if e=='raw_usb_write')
    assert after[28:]==before[28:],'stack guard overwritten'
    if payload_length==28:
        assert receive_result==[0] and raw_reads==[12,28] and not stream
        assert after[:28]==payload and terminal==['watchdog_callback']
        assert callbacks[-1]=={'watchdog_reset_args':[enablewdt,1]}
    elif payload_length==32:
        assert receive_result==[0xc0010006] and raw_reads==[12] and bytes(stream)==payload
        assert after==before and terminal==['shutdown_loop']
        assert callbacks==(['usb_disconnect','rtc_reset_time'] if stack_pattern==0 else [])
    return {'payload_bytes':payload_length,'initial_stack_fill':hex(stack_pattern),
      'enablewdt_word':enablewdt,'framed_header':struct.pack('<III',0xfeeeeeef,1,payload_length).hex(),
      'input_payload':payload.hex(),'raw_read_lengths':raw_reads,'receive_return':hex(receive_result[0]),
      'unconsumed_body_bytes':len(stream),'destination_unchanged':after==before,
      'stack_guard_unchanged':after[28:]==before[28:],'raw_ack_packets':raw_writes,
      'event_order':events,'callbacks':callbacks,'terminal':terminal[0],'passed':True}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--loader',type=Path,required=True);p.add_argument('--patched-da2',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.resolve() in (a.loader.resolve(),a.patched_da2.resolve()):p.error('output must not replace input')
    loader=a.loader.read_bytes();original=loader[0x7538a4:0x7538a4+0x5118c];patched=a.patched_da2.read_bytes()
    if (digest(loader),digest(original),digest(patched))!=(LOADER_SHA,DA_SHA,PATCHED_SHA):p.error('unrecognized artifact')
    matched=[]
    for name,lo,hi in SPANS:
        a0=original[lo-0x40000000:hi-0x40000000];b0=patched[lo-0x40000000:hi-0x40000000]
        assert a0==b0,name
        matched.append({'name':name,'start':hex(lo),'end':hex(hi),'sha256':digest(a0),'original_equals_patched':True})
    results=[]
    for name,blob in [('original',original),('actual_patched',patched)]:
        for length,fill,enable in [(28,0,0),(28,0xa5,0),(28,0xa5,1),(32,0,0),(32,0xa5,0)]:
            result=replay(blob,length,fill,enable);result['artifact']=name;results.append(result)
    result={'physical_hardware_tested':False,'loader_sha256':LOADER_SHA,'original_da2_sha256':DA_SHA,
            'actual_patched_da2_sha256':PATCHED_SHA,'matched_ranges':matched,
            'bounded_disassembly':disassemble(original,0x40000000,SPANS[:-1]),'cases':results,
            'conclusion':'32-byte host shutdown payload exceeds the exact28-byte receiver capacity; body is not copied or consumed. Handler ignores0xc0010006, sends zero ACK before field checks, then consults untouched stack fields. Exact28-byte payload reaches intended callback in controlled replay.',
            'limits':['Raw USB delivery, connected-USB status, USB/RTC/delay effects are modeled.','Receiver wrappers, framing checks, handler, ACK framing and capability functions execute original instructions.','No actual reset executed: stop at callback entry; reset acknowledgement is not boot success.','Untouched stack contents on the live phone are unknown; the tested fills demonstrate two cases, not a deterministic live outcome.','USB transient enumeration remains neither success nor failure evidence by itself.']}
    a.output.write_text(json.dumps(result,indent=2)+'\n');print('PASS:10 original/patched wire cases,32-byte rejection,zero ACK ordering,28-byte dispatch; no phone I/O')
if __name__=='__main__':main()
