#!/usr/bin/env python3
"""Execute the real linked probe and original vectors with modeled EL1 entry.

Unicorn executes all ordinary AArch64 instructions. System registers,
barriers, counter progression and exception entry/ERET are modeled explicitly;
this is not an interconnect, secure-world, or physical permission emulator.
"""
import hashlib
import os
from pathlib import Path
import struct
import subprocess

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_PROT_READ
from unicorn import arm64_const as regs

HERE = Path(__file__).resolve().parent
ADDRESSES = (0x110c00, 0x110c04, 0x110c08, 0x110c0c, 0x110ea0,
             0x10450000, 0x10450004, 0x10450008, 0x1045000c,
             0x10450010, 0x10450014, 0x10450018, 0x10451004)
EXTERNAL = (0x10000040, 0x10000090, 0x100010c8, 0x1000c23c, 0x1000c240,
            0x1000c248, 0x10006350, 0x10006358, 0x1001a010, 0x1001a024,
            0x1001a050, 0x1001a054, 0x1001a058)
EXTERNAL_VALUES = (0x20101, 0x1010201, 0, 0xd4800181, 0x81150000,
                   0x80000001, 0xffff0000, 0x12, 0, 0, 0, 0, 0)
IDENTITY = b'SSPM-OFFLINE-FIXTURE-IDENTITY-01'
MASK64 = (1 << 64) - 1


def register(name):
    return getattr(regs, 'UC_ARM64_REG_' + name.upper())


class Program:
    def __init__(self, directory):
        directory = Path(directory)
        clang = os.environ.get('IOS_CC', '/home/iscle/mt6762-ios-port/toolchain/bin/clang')
        self.command = [clang, '--target=aarch64-none-elf', '-mcpu=cortex-a53',
            '-mgeneral-regs-only', '-mstrict-align', '-ffixed-x28', '-ffreestanding',
            '-fno-builtin', '-fno-stack-protector', '-fno-pic', '-O2', '-Wall', '-Wextra',
            '-Werror', '-nostdlib', '-fuse-ld=lld', '-Wl,--build-id=none',
            '-Wl,-T,' + str(HERE / 'fixture.ld'), str(HERE.parent / 'start.S'),
            str(HERE / 'probe.c'), str(HERE / 'guard.S'), str(HERE / 'fixture.S'),
            '-o', str(directory / 'probe.elf')]
        subprocess.run(self.command, check=True, capture_output=True)
        self.elf = directory / 'probe.elf'
        self.sha256 = hashlib.sha256(self.elf.read_bytes()).hexdigest()
        self.instructions = {}
        self.symbols = {}
        self.segments = []
        disassembler = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        with self.elf.open('rb') as stream:
            elf = ELFFile(stream)
            self.symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
            for section in elf.iter_sections():
                if section['sh_flags'] & 4:
                    # The real Image header embeds data before vectors; decoding
                    # the entire section stops at those non-instruction bytes.
                    data = section.data()
                    for offset in range(0, len(data), 4):
                        self.instructions.update((i.address, i) for i in
                            disassembler.disasm(data[offset:offset+4], section['sh_addr']+offset))
            self.segments = [(s['p_vaddr'], s.data()) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        assert self.symbols['fixture_record'] == 0x40085400
        assert self.symbols['sspm_probe_vectors'] % 2048 == 0
        assert self.symbols['physical_vectors'] % 2048 == 0


class Machine:
    def __init__(self, program, *, fault_at=None, fault=None, stall_at=None,
                 values=None, tick_step=13, mutate=None, nested=False,
                 external_change=None, direct=False, index=0,
                 after_load_fault=None, stop_pc=None):
        self.program, self.symbols = program, program.symbols
        self.u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.base = self.symbols['image_start']
        self.end = self.symbols['image_end']
        self.u.mem_map(self.base, (self.end - self.base + 4095) & ~4095)
        for address, data in program.segments:
            self.u.mem_write(address, data)
        for page in sorted({a & ~4095 for a in ADDRESSES + EXTERNAL}):
            self.u.mem_map(page, 4096, UC_PROT_READ)
        for address, value in zip(EXTERNAL, EXTERNAL_VALUES):
            self.u.mem_write(address, struct.pack('<I', value))
        self.system = {'currentel': 4, 'spsel': 1, 'mpidr_el1': 0x80000000,
            'sctlr_el1': 0x30d00800, 'vbar_el1': self.symbols['physical_vectors'],
            'daif': 0x3c0, 'cntfrq_el0': 13000000, 'cntpct_el0': 1000,
            'esr_el1': 0, 'far_el1': 0, 'elr_el1': 0, 'spsr_el1': 0}
        for n in range(31):
            self.u.reg_write(register('x' + str(n)), 0x1100000000000000 + n * 0x10101)
        self.u.reg_write(regs.UC_ARM64_REG_X28, 0)
        self.u.reg_write(regs.UC_ARM64_REG_X30, self.symbols['fixture_return'])
        self.u.reg_write(regs.UC_ARM64_REG_SP, self.symbols['__stack_end'])
        self.u.reg_write(regs.UC_ARM64_REG_NZCV, 0xa0000000)
        self.direct = direct
        if direct:
            args = (index, self.symbols['fixture_output'], self.symbols['fixture_fault'])
            self.entry = self.symbols['sspm_guard_read']
        else:
            args = (self.symbols['fixture_record'], self.symbols['fixture_identity'])
            self.entry = self.symbols['sspm_probe_run']
        for n, value in enumerate(args):
            self.u.reg_write(register('x' + str(n)), value)
        self.fault_at, self.fault = fault_at, fault or {}
        self.stall_at, self.values = stall_at, values
        self.tick_step, self.mutate, self.nested = tick_step, mutate, nested
        self.external_change = external_change
        self.after_load_fault, self.stop_pc = after_load_fault, stop_pc
        self.attempts, self.device_reads, self.memory_writes = [], [], []
        self.system_writes, self.exceptions, self.erets, self.fatal = [], [], [], []
        self.returned = self.stalled = self.nested_injected = False
        self.instruction_count = 0
        self.minimum_sp = self.u.reg_read(regs.UC_ARM64_REG_SP)
        self.u.hook_add(UC_HOOK_CODE, self.code)
        self.u.hook_add(UC_HOOK_MEM_READ, self.read)
        self.u.hook_add(UC_HOOK_MEM_WRITE, self.write)

    def gprs(self):
        return [self.u.reg_read(register('x' + str(n))) for n in range(31)]

    def read(self, cpu, access, address, size, value, unused):
        if address < self.base or address >= self.end:
            assert address in ADDRESSES + EXTERNAL, hex(address)
            assert size == 4, (hex(address), size)
            self.device_reads.append(address)
            if address in EXTERNAL and self.external_change:
                self.external_change(self, address)

    def write(self, cpu, access, address, size, value, unused):
        assert self.base <= address and address + size <= self.end, ('unexpected hardware store', hex(address), size)
        self.memory_writes.append((address, size, value))

    def inject(self, address, overrides=None):
        override = overrides or {}
        interrupted = self.gprs()
        self.system['elr_el1'] = override.get('elr', address)
        self.system['esr_el1'] = override.get('esr', 0x96000010)
        self.system['far_el1'] = override.get('far', self.u.reg_read(regs.UC_ARM64_REG_X16))
        self.system['spsr_el1'] = override.get('spsr',
            self.u.reg_read(regs.UC_ARM64_REG_NZCV) | self.system['daif'] | 5)
        self.system['currentel'] = override.get('el', 4)
        self.system['spsel'] = override.get('spsel', 1)
        self.system['daif'] = 0x3c0
        if 'mpidr' in override: self.system['mpidr_el1'] = override['mpidr']
        self.exceptions.append({'gprs': interrupted, 'sp': self.u.reg_read(regs.UC_ARM64_REG_SP),
                                'elr': self.system['elr_el1']})
        slot = override.get('vector', 4)
        self.u.reg_write(regs.UC_ARM64_REG_PC, self.system['vbar_el1'] + slot * 128)

    def code(self, cpu, address, size, unused):
        self.instruction_count += 1
        sp = cpu.reg_read(regs.UC_ARM64_REG_SP)
        self.minimum_sp = min(self.minimum_sp, sp)
        assert sp % 16 == 0, ('misaligned SP', hex(address), hex(sp))
        assert self.symbols['__stack_start'] <= sp <= self.symbols['__stack_end']
        if address == self.symbols['fixture_return']:
            self.returned = True; cpu.emu_stop(); return
        if self.symbols['physical_vectors'] <= address < self.symbols['physical_vectors'] + 2048:
            self.fatal.append({'vector': (address-self.symbols['physical_vectors']) // 128,
                'gprs': self.gprs(), 'sp': sp, 'x28': cpu.reg_read(regs.UC_ARM64_REG_X28)})
            # Ordinary unsupported exceptions delegate to the actual old slot.
            # For nested cases execute its real branch + fatal recursion test.
            if not self.nested_injected:
                cpu.emu_stop(); return
        if address == self.symbols['physical_halt']:
            self.stalled = True; cpu.emu_stop(); return
        if address == self.stop_pc:
            self.stalled = True; cpu.emu_stop(); return
        if self.nested and not self.nested_injected and address == self.symbols['sspm_guard_sync'] + 8:
            self.nested_injected = True; self.inject(address); return
        if address == self.symbols['sspm_guard_load']:
            number = len(self.attempts)
            target = cpu.reg_read(regs.UC_ARM64_REG_X16)
            assert target in ADDRESSES
            self.attempts.append(target)
            if self.mutate: self.mutate(self, number)
            if number == self.stall_at:
                self.stalled = True; cpu.emu_stop(); return
            if number == self.fault_at:
                self.inject(address, self.fault); return
            value = self.values(number, target) if self.values else 0
            cpu.mem_write(target, struct.pack('<I', value))
        if address == self.symbols['sspm_guard_after_load'] and self.after_load_fault is not None:
            fault, self.after_load_fault = self.after_load_fault, None
            self.inject(address, fault); return
        instruction = self.program.instructions[address]
        operands = [p.strip() for p in instruction.op_str.split(',')]
        if instruction.mnemonic == 'mrs':
            name = operands[1].lower()
            if name == 'nzcv': value = cpu.reg_read(regs.UC_ARM64_REG_NZCV)
            else:
                value = self.system[name]
                if name == 'cntpct_el0': self.system[name] += self.tick_step
            cpu.reg_write(register(operands[0]), value)
            cpu.reg_write(regs.UC_ARM64_REG_PC, address+4)
        elif instruction.mnemonic == 'msr':
            name = operands[0].lower()
            if name == 'daifset':
                value = self.system['daif'] | (int(operands[1].lstrip('#'), 0) << 6)
                name = 'daif'
            else:
                value = 0 if operands[1] == 'xzr' else cpu.reg_read(register(operands[1]))
            if name == 'nzcv': cpu.reg_write(regs.UC_ARM64_REG_NZCV, value)
            else: self.system[name] = value
            self.system_writes.append((name, value))
            cpu.reg_write(regs.UC_ARM64_REG_PC, address+4)
        elif instruction.mnemonic == 'eret':
            context = struct.unpack('<8Q', cpu.mem_read(self.symbols['sspm_guard_context'], 64))
            assert context[0] == 0 and context[1] == 1, 'recovery must disarm before ERET'
            assert self.gprs() == self.exceptions[-1]['gprs'], 'handler GPR restoration'
            assert sp == self.exceptions[-1]['sp'], 'handler SP restoration'
            self.erets.append(self.system['elr_el1'])
            self.system['daif'] = self.system['spsr_el1'] & 0x3c0
            cpu.reg_write(regs.UC_ARM64_REG_NZCV, self.system['spsr_el1'] & 0xf0000000)
            cpu.reg_write(regs.UC_ARM64_REG_PC, self.system['elr_el1'])
        elif instruction.mnemonic in ('dsb', 'isb'):
            cpu.reg_write(regs.UC_ARM64_REG_PC, address+4)

    def run(self):
        self.initial_gprs = self.gprs()
        self.initial_sp = self.u.reg_read(regs.UC_ARM64_REG_SP)
        self.initial_nzcv = self.u.reg_read(regs.UC_ARM64_REG_NZCV)
        self.initial_daif = self.system['daif']
        self.initial_vbar = self.system['vbar_el1']
        self.u.emu_start(self.entry, self.end, count=100000)
        assert self.returned or self.stalled or self.fatal, 'fixture instruction budget exhausted'
        if self.returned:
            assert self.u.reg_read(regs.UC_ARM64_REG_SP) == self.initial_sp
            assert self.system['vbar_el1'] == self.initial_vbar
            assert self.system['daif'] == self.initial_daif
            if self.direct:
                assert self.gprs()[1:] == self.initial_gprs[1:]
                assert self.u.reg_read(regs.UC_ARM64_REG_NZCV) == self.initial_nzcv
        return self

    def record(self):
        return bytes(self.u.mem_read(self.symbols['fixture_record'], 1024))

    def output(self):
        return bytes(self.u.mem_read(self.symbols['fixture_output'], 4))

    def result(self):
        return self.u.reg_read(regs.UC_ARM64_REG_X0) & 0xffffffff
