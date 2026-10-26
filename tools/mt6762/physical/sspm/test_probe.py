#!/usr/bin/env python3
"""Real AArch64 C/assembly execution, exception predicates and record validation."""
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from unicorn import UcError
from unicorn import arm64_const as regs
from probe_fixture import Program, Machine, ADDRESSES, EXTERNAL, IDENTITY, register
from decode import decode


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='sspm-guard-tests-')
        cls.program = Program(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def decoded(self, machine):
        return decode(machine.record(), IDENTITY, self.program.symbols['sspm_guard_load'],
                      self.program.symbols['physical_vectors'])

    def test_link_layout_and_actual_vector_instructions(self):
        p = self.program
        load = p.instructions[p.symbols['sspm_guard_load']]
        self.assertEqual((load.mnemonic, load.op_str), ('ldr', 'w17, [x16]'))
        for slot in range(16):
            instruction = p.instructions[p.symbols['sspm_probe_vectors'] + slot*128]
            self.assertEqual(instruction.mnemonic, 'b')
            target = int(instruction.op_str.lstrip('#'), 0)
            expected = p.symbols['sspm_guard_sync'] if slot == 4 else p.symbols['physical_vectors'] + slot*128
            self.assertEqual(target, expected)
        self.assertEqual(p.symbols['fixture_record'], 0x40085400)
        self.assertEqual(p.symbols['__stack_end'] - p.symbols['__stack_start'], 65536)
        self.assertEqual(p.symbols['sspm_probe_vectors'] % 2048, 0)
        self.assertEqual(p.symbols['physical_vectors'] % 2048, 0)

    def test_all_indices_preserve_gprs_flags_stack_daif_vbar(self):
        for index in range(13):
            for abort in (False, True):
                with self.subTest(index=index, abort=abort):
                    machine = Machine(self.program, direct=True, index=index,
                                      fault_at=0 if abort else None, values=lambda n, a: 0x78563412)
                    prior_fault = bytes(machine.u.mem_read(machine.symbols['fixture_fault'], 32))
                    machine.run()  # fixture checks every GPR, NZCV, SP, DAIF/VBAR
                    self.assertEqual(machine.result(), 0xffffffff if abort else 0)
                    self.assertEqual(machine.output(), b'\xa5'*4 if abort else b'\x12\x34\x56\x78')
                    self.assertEqual(machine.attempts, [ADDRESSES[index]])
                    context = struct.unpack('<8Q', machine.u.mem_read(machine.symbols['sspm_guard_context'], 64))
                    self.assertEqual(context[:2], (0, 0))
                    if abort:
                        self.assertEqual(machine.erets, [machine.symbols['sspm_guard_failed']])
                    else:
                        self.assertEqual(bytes(machine.u.mem_read(machine.symbols['fixture_fault'], 32)), prior_fault)
                    self.assertTrue({k for k, v in machine.system_writes} <= {'vbar_el1', 'elr_el1', 'nzcv', 'daif'})

    def test_real_c_two_pass_zero_nonzero_and_changing_data(self):
        for values, classification, stable in ((None, 'completed_zero', True),
                (lambda n, a: a, 'completed_nonzero', True),
                (lambda n, a: a+n, 'completed_nonzero', False)):
            with self.subTest(classification=classification, stable=stable):
                machine = Machine(self.program, values=values).run()
                result = self.decoded(machine)
                self.assertEqual(result['classification'], classification)
                self.assertEqual(machine.attempts, list(ADDRESSES)*2)
                self.assertEqual(result['completed_reads'], 26)
                self.assertEqual(result['screen_count'], 6)
                self.assertEqual(len(machine.device_reads), 104)
                self.assertEqual(result['sequence'], 60)
                self.assertTrue(all(w['stable'] == stable for w in result['words']))
                self.assertFalse(result['sspm_ownership_granted'] or result['dvfs_granted'])

    def test_fault_at_every_one_of_26_loads_stops_first(self):
        for position in range(26):
            with self.subTest(position=position):
                machine = Machine(self.program, fault_at=position, values=lambda n, a: n+1).run()
                result = self.decoded(machine)
                self.assertEqual(result['classification'], 'synchronous_abort')
                self.assertEqual(result['completed_reads'], position)
                self.assertEqual(machine.attempts, (list(ADDRESSES)*2)[:position+1])
                self.assertEqual([a for a in machine.device_reads if a in ADDRESSES],
                                 (list(ADDRESSES)*2)[:position])
                self.assertEqual(len(machine.erets), 1)
                self.assertEqual(machine.result(), 3)

    def test_syndrome_cpu_pc_far_predicate_negatives_are_fatal(self):
        pc = self.program.symbols['sspm_guard_load']
        cases = [{'elr': pc+4}, {'el': 8}, {'spsel': 0}, {'mpidr': 0x80000001},
                 {'spsr': 0x3c4}, {'spsr': 0x2c5}, {'far': ADDRESSES[0]+4}]
        cases += [{'esr': value} for value in (0x94000010, 0x92000010, 0x96000004,
                  0x9600000d, 0x96000021, 0x96000050, 0x96000090, 0x96000110, 0x96000410)]
        for fault in cases:
            with self.subTest(fault=fault):
                machine = Machine(self.program, direct=True, fault_at=0, fault=fault).run()
                self.assertTrue(machine.fatal)
                self.assertFalse(machine.returned or machine.erets)
                self.assertEqual(machine.output(), b'\xa5'*4)
                self.assertEqual(machine.fatal[0]['gprs'], machine.exceptions[0]['gprs'])
        # EA is implementation-defined classification, not an admission veto.
        machine = Machine(self.program, fault_at=0, fault={'esr': 0x96000210}).run()
        self.assertEqual(self.decoded(machine)['fault']['esr'], '0x96000210')

    def test_wrong_vector_and_nested_fault_delegate_original_fatal(self):
        for slot in range(16):
            if slot == 4: continue
            with self.subTest(slot=slot):
                machine = Machine(self.program, fault_at=0, fault={'vector': slot}).run()
                self.assertEqual(machine.fatal[0]['vector'], slot)
                self.assertFalse(machine.erets or machine.returned)
                self.assertEqual(self.decoded(machine)['classification'], 'incomplete')
        machine = Machine(self.program, fault_at=0, nested=True).run()
        self.assertTrue(machine.nested_injected and machine.stalled)
        self.assertEqual(len(machine.exceptions), 2)
        self.assertEqual(machine.fatal[0]['x28'], 1)
        self.assertFalse(machine.erets)
        # The real existing fatal path reaches physical_halt before UART/store.
        self.assertEqual(self.decoded(machine)['classification'], 'incomplete')

    def test_context_corruption_cannot_recover(self):
        cases = ((0, 0), (8, 1), (16, ADDRESSES[0]+4), (24, 13), (48, 0x80000001))
        for offset, value in cases:
            def mutate(machine, number, offset=offset, value=value):
                machine.u.mem_write(machine.symbols['sspm_guard_context']+offset, struct.pack('<Q', value))
            with self.subTest(offset=offset):
                machine = Machine(self.program, direct=True, fault_at=0, mutate=mutate).run()
                self.assertTrue(machine.fatal)
                self.assertFalse(machine.erets)
                self.assertEqual(machine.output(), b'\xa5'*4)
        def different_register(machine, number):
            machine.u.reg_write(regs.UC_ARM64_REG_X16, ADDRESSES[1])
        machine = Machine(self.program, direct=True, fault_at=0, mutate=different_register).run()
        self.assertTrue(machine.fatal)
        self.assertFalse(machine.erets)

    def test_after_load_serror_or_barrier_abort_is_not_recovered(self):
        for fault in ({'vector': 7, 'esr': 0xbe000000}, {'vector': 4, 'esr': 0x96000010}):
            with self.subTest(fault=fault):
                machine = Machine(self.program, after_load_fault=fault).run()
                self.assertEqual([a for a in machine.device_reads if a in ADDRESSES], [ADDRESSES[0]])
                self.assertEqual(machine.exceptions[0]['elr'], machine.symbols['sspm_guard_after_load'])
                self.assertTrue(machine.fatal)
                self.assertFalse(machine.erets or machine.returned)
                result = self.decoded(machine)
                self.assertEqual(result['completed_reads'], 0)
                self.assertEqual(result['classification'], 'incomplete')
                self.assertFalse(result['fault_committed'])

    def test_interrupted_fault_metadata_is_not_a_committed_abort(self):
        # Stop after each of the actual handler's two metadata STP instructions.
        stores = [i.address for i in self.program.instructions.values()
                  if self.program.symbols['sspm_guard_sync'] <= i.address < self.program.symbols['sspm_guard_sync']+512
                  and i.mnemonic == 'stp' and i.op_str in ('x14, x15, [x9]', 'x13, x12, [x9, #0x10]')]
        self.assertEqual(len(stores), 2)
        for pc in stores:
            with self.subTest(pc=hex(pc)):
                machine = Machine(self.program, fault_at=0, stop_pc=pc+4).run()
                result = self.decoded(machine)
                self.assertEqual(result['classification'], 'incomplete')
                self.assertFalse(result['fault_committed'] or machine.returned or machine.erets)
                self.assertEqual(result['fault']['esr'], '0x96000010')

    def test_entry_and_buffer_refusal_precedes_protected_access(self):
        states = [('currentel', 8), ('spsel', 0), ('mpidr_el1', 0x80000001),
                  ('mpidr_el1', 0x80010000), ('mpidr_el1', 0x180000000),
                  ('sctlr_el1', 1), ('sctlr_el1', 4), ('sctlr_el1', 1 << 25),
                  ('daif', 0), ('vbar_el1', 0)]
        for name, value in states:
            with self.subTest(state=name, value=value):
                machine = Machine(self.program, direct=True)
                machine.system[name] = value
                machine.run()
                self.assertEqual(machine.result(), 0xfffffffe)
                self.assertFalse(machine.attempts or machine.device_reads)
        for index in (13, 0xffffffff, 1 << 32):
            machine = Machine(self.program, direct=True, index=index).run()
            self.assertEqual(machine.result(), 0xfffffffe)
            self.assertFalse(machine.attempts)
        machine = Machine(self.program, direct=True)
        machine.u.reg_write(regs.UC_ARM64_REG_X28, 1)
        machine.run(); self.assertEqual(machine.result(), 0xfffffffe)
        for offset in (0, 8):
            machine = Machine(self.program, direct=True)
            machine.u.mem_write(machine.symbols['sspm_guard_context']+offset, struct.pack('<Q', 1))
            machine.run()
            self.assertEqual(machine.result(), 0xfffffffe)
            self.assertFalse(machine.attempts or machine.device_reads)
            self.assertEqual([name for name, value in machine.system_writes], ['nzcv'])
        for arg in (1, 2):
            for kind in ('device', 'unaligned', 'end', 'context', 'wrapper_frame', 'exception_frame'):
                with self.subTest(arg=arg, kind=kind):
                    machine = Machine(self.program, direct=True, fault_at=0)
                    addresses = {'device': ADDRESSES[0], 'unaligned': machine.symbols['fixture_output']+1,
                        'end': machine.end, 'context': machine.symbols['sspm_guard_context'],
                        'wrapper_frame': machine.end-32, 'exception_frame': machine.end-400}
                    address = addresses[kind]
                    machine.u.reg_write(register('x'+str(arg)), address)
                    if kind == 'exception_frame':
                        machine.u.mem_write(address, bytes([0x5a])*32)
                    machine.run()
                    self.assertEqual(machine.result(), 0xfffffffe)
                    self.assertFalse(machine.attempts or machine.device_reads)
                    if kind == 'exception_frame':
                        self.assertEqual(bytes(machine.u.mem_read(address, 32)), bytes([0x5a])*32)
        machine = Machine(self.program, direct=True)
        machine.u.reg_write(regs.UC_ARM64_REG_X1, machine.symbols['fixture_fault'])
        machine.run(); self.assertEqual(machine.result(), 0xfffffffe)

    def test_c_entry_refusal_and_invalid_record_never_probe_hardware(self):
        for key, value in (('currentel', 8), ('spsel', 0), ('cntfrq_el0', 0), ('daif', 0),
                           ('vbar_el1', 0), ('mpidr_el1', 0x80000001), ('sctlr_el1', 1)):
            with self.subTest(key=key):
                machine = Machine(self.program)
                machine.system[key] = value
                machine.run()
                result = self.decoded(machine)
                self.assertEqual(result['reason'], 'entry')
                self.assertEqual(machine.result(), 4)
                self.assertFalse(machine.device_reads or machine.attempts)
        for arg, value in ((0, ADDRESSES[0]), (0, 0x40085401), (1, ADDRESSES[0]), (1, 0x40085400)):
            machine = Machine(self.program)
            machine.u.reg_write(register('x'+str(arg)), value)
            machine.run()
            self.assertEqual(machine.result(), 4)
            self.assertFalse(machine.device_reads or machine.attempts)
            self.assertEqual(machine.record(), bytes(1024))

    def test_external_profile_mismatch_stops_and_security_is_not_a_grant(self):
        for index in range(8):
            machine = Machine(self.program)
            address = EXTERNAL[index]
            original, = struct.unpack('<I', machine.u.mem_read(address, 4))
            bit = 1 << 17 if index == 2 else 1
            machine.u.mem_write(address, struct.pack('<I', original ^ bit))
            machine.run(); result = self.decoded(machine)
            self.assertEqual(result['reason'], 'external_profile')
            self.assertEqual(result['bad_screen_word'], index)
            self.assertFalse(machine.attempts)
        def change_second_screen(machine, address):
            if address == EXTERNAL[0] and machine.device_reads.count(address) == 2:
                machine.u.mem_write(address, struct.pack('<I', 0))
        machine = Machine(self.program, external_change=change_second_screen).run()
        self.assertEqual(self.decoded(machine)['completed_reads'], 5)
        self.assertEqual(machine.attempts, list(ADDRESSES[:5]))
        machine = Machine(self.program)
        for i, address in enumerate(EXTERNAL[8:]):
            machine.u.mem_write(address, struct.pack('<I', i+1))
        machine.run(); result = self.decoded(machine)
        self.assertEqual(result['classification'], 'completed_zero')
        self.assertFalse(result['sspm_ownership_granted'])

    def test_deadline_reversed_frozen_time_and_stalled_bus(self):
        machine = Machine(self.program, tick_step=130001).run()
        self.assertEqual(self.decoded(machine)['reason'], 'dispatch_budget')
        self.assertFalse(machine.attempts or machine.device_reads)
        def reverse(machine, number):
            machine.system['cntpct_el0'] = 0
        machine = Machine(self.program, mutate=reverse).run()
        result = self.decoded(machine)
        self.assertEqual(result['reason'], 'reversed_time')
        self.assertEqual(result['completed_reads'], 1)
        machine = Machine(self.program, tick_step=0).run()
        self.assertEqual(self.decoded(machine)['completed_reads'], 26)
        self.assertLess(machine.instruction_count, 20000)
        for position in (0, 12, 25):
            machine = Machine(self.program, stall_at=position).run()
            result = self.decoded(machine)
            self.assertEqual(result['classification'], 'incomplete')
            self.assertEqual(result['completed_reads'], position)
            self.assertFalse(machine.returned or machine.erets)
            self.assertTrue(machine.stalled)

    def test_physical_address_mapping_and_uncontained_external_screen_fault(self):
        machine = Machine(self.program)
        machine.u.mem_unmap(EXTERNAL[0] & ~4095, 4096)
        with self.assertRaises(UcError): machine.run()
        self.assertFalse(machine.attempts or machine.erets)
        self.assertEqual(self.decoded(machine)['classification'], 'incomplete')

    def test_decoder_rejects_corruption_identity_layout_and_wrong_fault_pc(self):
        machine = Machine(self.program).run()
        original = machine.record()
        changes = [(0, '<B', 0), (8, '<I', 2), (12, '<I', 512), (16, '<B', 0),
            (52, '<I', 0), (60, '<I', 0), (68, '<I', 25), (72, '<I', 13),
            (80, '<I', 7), (104, '<Q', 1), (112, '<Q', 1), (120, '<Q', 1),
            (204, '<I', 0), (216, '<Q', 1), (224, '<Q', 0), (232, '<Q', 0),
            (244, '<I', 1), (256, '<I', ADDRESSES[1]), (268, '<I', 2), (880, '<B', 1)]
        for offset, form, value in changes:
            with self.subTest(offset=offset):
                raw = bytearray(original); struct.pack_into(form, raw, offset, value)
                with self.assertRaises(ValueError):
                    decode(raw, IDENTITY, machine.symbols['sspm_guard_load'], machine.symbols['physical_vectors'])
        with self.assertRaises(ValueError):
            decode(original[:-1], IDENTITY, machine.symbols['sspm_guard_load'], machine.symbols['physical_vectors'])
        fault = Machine(self.program, fault_at=0).run()
        with self.assertRaises(ValueError):
            decode(fault.record(), IDENTITY, fault.symbols['sspm_guard_load']+4, fault.symbols['physical_vectors'])
        path = Path(self.directory.name) / 'record.bin'; path.write_bytes(original)
        command = ['python3', str(Path(__file__).with_name('decode.py')), str(path),
                   '--identity', IDENTITY.hex(), '--load-pc', hex(machine.symbols['sspm_guard_load']),
                   '--physical-vectors', hex(machine.symbols['physical_vectors'])]
        parsed = json.loads(subprocess.check_output(command, text=True))
        self.assertEqual(parsed['classification'], 'completed_zero')


if __name__ == '__main__':
    unittest.main(verbosity=2)
