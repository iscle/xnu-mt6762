#!/usr/bin/env python3
"""Audit exact LK synchronous eMMC completion; no phone access or payload."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_R0

SHA = '5badc0dc942b0babdca3da13c7e07f3b5f1e57b66d503414b7f80effe8ce891a'
BASE = 0x47fffe00
REG = 0x11230000
HOST, PRIVATE, STACK, RETURN = 0x60001000, 0x60002000, 0x6000f000, 0x60000000


def replay_stop(blob, busy_reads):
    """Execute original stop and its helpers; emulate DMA status only."""
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    u.mem_map(0x48000000, 0x400000)
    u.mem_write(0x48000000, blob[0x200:])
    u.mem_map(REG, 0x1000)
    u.mem_map(RETURN, 0x10000)
    def write(address, value):
        u.mem_write(address, struct.pack('<I', value))
    def read(address):
        return struct.unpack('<I', u.mem_read(address, 4))[0]
    write(HOST + 0x28, REG)
    write(HOST + 0x78, PRIVATE)
    write(REG, 0x02200191)  # Existing DMA mode; preserve all except PIO bit.
    write(REG + 0x10, 0xd100)
    for off in (0x68, 0x6c, 0x84, 0x88):
        write(PRIVATE + off, 0x12345678)
    status_reads, writes = [], []
    def on_read(cpu, access, address, size, value, unused):
        if address == REG + 0x9c:
            assert size == 4
            busy = busy_reads is None or len(status_reads) < busy_reads
            write(address, 5 if busy else 4)
            status_reads.append(5 if busy else 4)
    def on_write(cpu, access, address, size, value, unused):
        if REG <= address < REG + 0x1000:
            assert size == 4
            writes.append([hex(address), hex(value)])
    u.hook_add(UC_HOOK_MEM_READ, on_read)
    u.hook_add(UC_HOOK_MEM_WRITE, on_write)
    u.reg_write(UC_ARM_REG_SP, STACK)
    u.reg_write(UC_ARM_REG_LR, RETURN | 1)
    u.reg_write(UC_ARM_REG_R0, HOST)
    u.emu_start(0x48050ca1, RETURN, count=2000)
    returned = u.reg_read(UC_ARM_REG_PC) == RETURN
    if busy_reads is None:
        assert not returned and len(status_reads) > 100
        assert writes == [[hex(REG + 0x98), '0x2']]
        assert read(REG) == 0x02200191
        assert read(REG + 0x10) == 0xd100
        assert all(read(PRIVATE + off) == 0x12345678 for off in (0x68, 0x6c, 0x84, 0x88))
    else:
        assert returned and len(status_reads) == busy_reads + 1
        assert writes == [[hex(REG + 0x98), '0x2'], [hex(REG), '0x2200199'],
                          [hex(REG + 0x10), '0x100']]
        assert all(read(PRIVATE + off) == 0 for off in (0x68, 0x6c, 0x84, 0x88))
    return dict(busy_reads=busy_reads, returned=returned, passed=True,
                dma_status_reads=len(status_reads), ordered_mmio_writes=writes)


def audit(blob):
    if hashlib.sha256(blob).hexdigest() != SHA:
        raise ValueError('Require exact stock LK')
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    ranges = [(0x48050fc4, 0x4805101c), (0x48050da8, 0x48050fc0),
              (0x48050ca0, 0x48050cf4), (0x48050924, 0x48050936),
              (0x4804e0c8, 0x4804e0d4)]
    decoded = {}
    spans = []
    for lo, hi in ranges:
        raw = blob[lo-BASE:hi-BASE]
        instructions = list(md.disasm(raw, lo))
        assert sum(i.size for i in instructions) == len(raw)
        decoded.update({i.address: (i.mnemonic, i.op_str) for i in instructions})
        spans.append(dict(start=hex(lo), end=hex(hi), sha256=hashlib.sha256(raw).hexdigest()))
    calls = {0x48051012: 0x48050da8, 0x48050e66: 0x48050c68,
             0x48050e70: 0x48050cf4, 0x48050e78: 0x48050ca0,
             0x48050e84: 0x48050798, 0x48050eb0: 0x4804eea0}
    for address, target in calls.items():
        assert decoded[address] == ('bl', f'#{target:#x}')
    assert decoded[0x48050dde] == ('str.w', 'r1, [sl, #0x74]')
    return dict(stock_lk_sha256=SHA, bounded_code=spans,
        callback='0x48050fc5', transfer='0x48050da8',
        ordered_direct_calls={hex(a): hex(t) for a, t in calls.items()},
        cases=[replay_stop(blob, n) for n in (0, 1, 7, None)],
        findings=[
            'Captured blk_read resolves to this synchronous DMA callback.',
            'The normal transfer path calls DMA start, wait, stop and cache maintenance before return; no FEATURE_NONBLOCKING_RW early return is present at this call site.',
            'DMA stop polls DMA_CFG bit0 clear before restoring PIO bit3, masking its data IRQs and clearing private descriptor bookkeeping.',
            'host+0x74 is a debug command pointer assigned from the caller stack and not cleared; nonzero alone does not prove an outstanding command.',
        ],
        limitations=[
            'Unicorn models DMA completion; this is not a physical storage test.',
            'The stock stop wait is unbounded; it is audited, never called by the new driver.',
            'Runtime handoff still requires captured exact-LK linkage, idle controller/DMA/FIFO, masked GIC, clocks/pads/rails, and live CMD13/EXT_CSD.',
        ], phone_access=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lk', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    result = audit(a.lk.read_bytes())
    with a.out.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print('PASS: exact-LK synchronous call sites and four original DMA-stop cases')


if __name__ == '__main__':
    main()
