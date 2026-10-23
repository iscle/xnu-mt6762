#!/usr/bin/env python3
"""Retain only memory/boot-handoff facts from a supplied expdb image.

These are historical ASCII boot-log observations, not live measurements.
No general log contents, device identifiers or private partition data are exported.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('expdb', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
data = a.expdb.read_bytes()
patterns = (
    r'^total_dram_size: 0x[0-9a-fA-F]+, max_dram_size: 0x[0-9a-fA-F]+$',
    r'^.*Memory: [0-9]+K/[0-9]+K available \(.*\)$',
    r'^.*\[BLOCK_TAG\] DRAM: 0x[0-9a-fA-F]+ - 0x[0-9a-fA-F]+, size: 0x[0-9a-fA-F]+$',
    r'^.*LK_LOG_STORE:dram pl/lk log buff mapping start addr = 0x[0-9a-fA-F]+, size = 0x[0-9a-fA-F]+$',
    r'^RAM_CONSOLE mrdump_addr:0x[0-9a-fA-F]+, mrdump_size:0x[0-9a-fA-F]+, dram_addr:0x[0-9a-fA-F]+, dram_size:0x[0-9a-fA-F]+$',
    r'^RAM_CONSOLE\. boot_arg\(PL2LK\): sram_addr:0x[0-9a-fA-F]+, sram_size:0x[0-9a-fA-F]+, def_type:0x[0-9a-fA-F]+, memory_info_offset:0x[0-9a-fA-F]+$',
)
found = []
for m in re.finditer(rb'[\x20-\x7e]{8,}', data):
    line = m.group().decode('ascii')
    if any(re.fullmatch(pattern, line) for pattern in patterns):
        found.append({'file_offset': m.start(), 'text': line})
dram_sizes = sorted({int(m.group(1), 16) for row in found
                     if (m := re.match(r'total_dram_size: (0x[0-9a-fA-F]+)', row['text']))})
report = {
    'source': str(a.expdb.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
    'evidence_type': 'historical ASCII boot logs with exact image offsets',
    'observations': found,
    'reported_total_dram_bytes': dram_sizes,
    'inference': ('Consistent retained total DRAM reports; compare with the static DTB and live boot map.'
                  if len(dram_sizes) == 1 else 'No unique total DRAM value established.'),
    'limitations': ['No live hardware measurement.', 'Bootloader reserved regions must still be reconciled before physical boot.',
                   'Only the explicit memory and handoff line patterns above were retained.'],
}
a.output.write_text(json.dumps(report, indent=2) + '\n')
print(f'{len(found)} bounded observations saved to {a.output}')
