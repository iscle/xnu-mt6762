#!/usr/bin/env python3
"""Execute the exact bounded stock calibration function locally with Unicorn.

No phone interaction. Only known Image digest is accepted; printk and profiling
are intercepted. The original calibration instructions are not modified.
Usage: emulate_stock_thermal.py path/to/Image > evidence/stock-thermal-slopes.json
"""
import hashlib
import json
import struct
import sys
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC

blob = Path(sys.argv[1]).read_bytes()
digest = hashlib.sha256(blob).hexdigest()
assert digest == '82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b'
base = 0xffffff8008080000
function = 0xffffff800888abf0
globals_base = 0xffffff8009a8f000
cases = []
for slope in (0, 1, 7, 63):
    for sign in (0, 1):
        machine = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        machine.mem_map(base, 0x2000000)
        machine.mem_write(base, blob)
        machine.mem_map(0x100000, 0x10000)
        machine.reg_write(UC_ARM64_REG_SP, 0x10f000)
        machine.reg_write(UC_ARM64_REG_LR, 0x200000)
        instruction_count = [0]

        def instruction(uc, address, size, unused):
            instruction_count[0] += 1
            if address in (0xffffff800809ef9c, 0xffffff8008125b2c):
                uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
            elif not function <= address <= 0xffffff800888adc8:
                raise RuntimeError(f'unexpected instruction at {address:x}')

        machine.hook_add(UC_HOOK_CODE, instruction)
        for offset, value in ((0x84, slope), (0x8c, 1588), (0x90, 1526),
                              (0x94, 1534), (0x98, 55), (0x9c, sign)):
            machine.mem_write(globals_base + offset, struct.pack('<I', value))
        machine.emu_start(function, 0x200000, count=1000)
        assert machine.reg_read(UC_ARM64_REG_PC) == 0x200000
        denominators = struct.unpack('<3i', machine.mem_read(0xffffff8009852bdc, 12))
        intercepts = [struct.unpack('<i', machine.mem_read(globals_base + off, 4))[0]
                      for off in (0xa4, 0xac, 0xb4)]
        cases.append(dict(slope=slope, sign=sign, denominators=denominators,
                          intercepts=intercepts, instructions=instruction_count[0]))
print(json.dumps(dict(image_sha256=digest, function_va=hex(function),
                     method='original AArch64 instructions in Unicorn; only printk/_mcount intercepted',
                     physical_hardware_tested=False, cases=cases), indent=2))
