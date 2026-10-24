#!/usr/bin/env python3
"""Pinned offline preloader disassembly and exact stack-epilogue replay.

Reads a local dump only. Does not connect to USB, emit patches, or run the
preloader boot flow. Unicorn executes only the original save/restore snippets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_R5,
    UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
    UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

SHA256 = '7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674'
BASE = 0x200710
RANGES = [
    ('entry_cache_state', 0x201064, 0x201098, CS_MODE_ARM),
    ('entry_icache_enable', 0x2010d8, 0x2010f8, CS_MODE_ARM),
    ('cache_helpers', 0x201174, 0x2011b0, CS_MODE_ARM),
    ('usbdl_prologue', 0x202bf0, 0x202c02, CS_MODE_THUMB),
    ('dispatch_prefix', 0x202c90, 0x202cc2, CS_MODE_THUMB),
    ('default_to_loop', 0x202d28, 0x202d46, CS_MODE_THUMB),
    ('write32_body', 0x202dcc, 0x202e48, CS_MODE_THUMB),
    ('write32_status', 0x203118, 0x203122, CS_MODE_THUMB),
    ('shared_status', 0x202fd8, 0x202fe0, CS_MODE_THUMB),
    ('timeout_epilogue', 0x203168, 0x203174, CS_MODE_THUMB),
    ('caller_after_return', 0x21a220, 0x21a27c, CS_MODE_THUMB),
    ('region_whitelist', 0x227888, 0x227906, CS_MODE_THUMB),
    ('region_check', 0x227910, 0x22792c, CS_MODE_THUMB),
]


def inspect(data):
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('preloader identity mismatch; no address-based analysis performed')
    records = {}
    for name, start, end, mode in RANGES:
        records[name] = [dict(address=hex(i.address), bytes=i.bytes.hex(),
                              mnemonic=i.mnemonic, operands=i.op_str)
                         for i in Cs(CS_ARCH_ARM, mode).disasm(data[start-BASE:end-BASE], start)]
    targets = {hex(cmd):hex(0x202cc2 + 2 * struct.unpack_from('<H', data,
        0x202cc2-BASE + (cmd-0xc4)*2)[0]) for cmd in [0xd4, 0xd5, 0xd6, 0xd7]}
    assert targets == {'0xd4':'0x202dcc', '0xd5':'0x202fe8',
                       '0xd6':'0x202d0a', '0xd7':'0x202e48'}
    assert data[0x202d0a-BASE:0x202d0c-BASE] == bytes.fromhex('c1e7')
    assert records['timeout_epilogue'][-1]['operands'] == '{r4, r5, r6, r7, pc}'
    return records, targets


def replay_epilogue(data):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0x200000, 0x40000)
    uc.mem_write(BASE, data[:0x40000-(BASE-0x200000)])
    uc.mem_map(0x50000000, 0x4000)
    uc.mem_map(0x60000000, 0x1000)
    regs = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
            UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]
    expected = [0x44000000 + n for n in range(len(regs))]
    for reg, value in zip(regs, expected):
        uc.reg_write(reg, value)
    original_sp = 0x50003000
    uc.reg_write(UC_ARM_REG_SP, original_sp)
    uc.reg_write(UC_ARM_REG_LR, 0x60000001)
    uc.emu_start(0x202bf1, 0x202bfa, count=4)
    saved_sp = uc.reg_read(UC_ARM_REG_SP)
    assert saved_sp == original_sp - 0x60
    for reg in regs:
        uc.reg_write(reg, 0xdeadbeef)
    uc.emu_start(0x203169, 0x60000000, count=4)
    assert [uc.reg_read(reg) for reg in regs] == expected
    assert uc.reg_read(UC_ARM_REG_SP) == original_sp
    assert uc.reg_read(UC_ARM_REG_PC) == 0x60000000
    assert uc.reg_read(UC_ARM_REG_R0) == 0xffffffff
    return dict(passed=True, execution='original four-instruction prologue and four-instruction epilogue only',
                saved_frame_bytes=0x60, restored_callee_saved_registers=True,
                restored_stack=True, returned_to_sentinel=True,
                hardware_execution=False, cache_coherency_tested=False,
                normal_boot_chain_executed=False)


def replay_write_regions(data):
    """Execute only pure range comparisons against original constant tables."""
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0x200000, 0x40000)
    uc.mem_write(BASE, data[:0x40000-(BASE-0x200000)])
    uc.mem_map(0x50000000, 0x4000)
    uc.mem_map(0x60000000, 0x1000)
    result = []
    for address, expected in [(0x202d40, False), (0x50002000, False),
                              (0x48000000, False), (0x40200000, False),
                              (0x10007000, True), (0x1001a080, True)]:
        uc.reg_write(UC_ARM_REG_SP, 0x50003000)
        uc.reg_write(UC_ARM_REG_LR, 0x60000001)
        uc.reg_write(UC_ARM_REG_R0, address)
        uc.reg_write(UC_ARM_REG_R1, 4)
        uc.reg_write(UC_ARM_REG_R2, 0)  # OP_WRITE, no memory access performed.
        uc.emu_start(0x227911, 0x60000000, count=300)
        assert uc.reg_read(UC_ARM_REG_PC) == 0x60000000
        status = uc.reg_read(UC_ARM_REG_R0)
        assert (status == 0) == expected
        result.append(dict(address=hex(address), length=4, permitted=status == 0, status=hex(status)))
    table = [dict(address=hex(a), size=hex(n)) for a, n in struct.iter_unpack('<II',
        data[0x238e68-BASE:0x238e78-BASE])]
    return dict(passed=True, original_write_whitelist=table, cases=result,
                actual_memory_writes=False, hardware_execution=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preloader', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('new output path required')
    data = args.preloader.read_bytes()
    records, targets = inspect(data)
    report = dict(preloader_sha256=SHA256, address_mapping='VA=file_offset+0x200710',
                  authority='offline Capstone disassembly and bounded Unicorn snippet replay',
                  rea='firmware inspector unavailable: REA_BINWALK_COMMAND missing; no REA Evidence claimed',
                  disassembly=records, command_targets=targets,
                  epilogue_replay=replay_epilogue(data),
                  write_region_replay=replay_write_regions(data),
                  established_resume_command=False, usable_ram_patch_generated=False)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['epilogue_replay']))


if __name__ == '__main__':
    main()
