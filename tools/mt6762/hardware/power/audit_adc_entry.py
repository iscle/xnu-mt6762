"""Audit the additional passive ADC register inventory; saved files only.

The existing PMIC13 record and capture33 remain independent historical
evidence. This audit does not claim the new ADC record has run physically.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
XNU = HERE.parents[3]
PORT = XNU.parents[2] if XNU.parent.name == 'xnu-src' else XNU.parent
ROWS = [('HWCID', 0x8), ('SWCID', 0xa),
        ('AUXADC_DIG_1_ELR0', 0x10de), ('AUXADC_DIG_1_ELR1', 0x10e0),
        ('AUXADC_CON0', 0x1120), ('AUXADC_CON1', 0x1126),
        ('AUXADC_CON2', 0x1128), ('AUXADC_CON5', 0x112e),
        ('AUXADC_CON7', 0x1132), ('AUXADC_CON9', 0x1136),
        ('AUXADC_CON11', 0x113a), ('AUXADC_CON12', 0x113c),
        ('AUXADC_ANA_CON0', 0x1008), ('AUXADC_DIG_3_ELR0', 0x11a2),
        ('AUXADC_DIG_3_ELR1', 0x11a4), ('AUXADC_DIG_3_ELR2', 0x11a6),
        ('AUXADC_DIG_3_ELR3', 0x11a8), ('AUXADC_DIG_3_ELR4', 0x11aa),
        ('AUXADC_DIG_3_ELR5', 0x11ac)]


def identity(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def array(text, name):
    without_comments = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    match = re.search(r'\b' + re.escape(name) + r'\[[^]]*\]\s*=\s*\{([^}]+)\}', without_comments)
    assert match, name
    return [int(word.strip(), 0) for word in match[1].split(',')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bsp', type=Path, default=Path('/mnt/0da18f53-c547-40a2-a7c3-b08e84d1aab4/alps/aosp-docker/workspace'))
    parser.add_argument('--output', type=Path, default=HERE / 'adc-entry-evidence.json')
    args = parser.parse_args()
    registers = args.bsp / 'kernel-4.14/include/linux/mfd/mt6357/registers.h'
    source = registers.read_text()
    catalog = []
    for label, address in ROWS:
        match = re.search(r'^#define MT6357_' + label + r'\s+\(MT6357_PMIC_REG_BASE\+0x([0-9a-f]+)\)', source, re.M)
        assert match and int(match[1], 16) == address, (label, address)
        assert not any(part in label for part in ['_SET', '_CLR', 'RQST', 'FIFO', 'STATUS'])
        catalog.append(dict(label=label, address=f'{address:04x}', width=2,
                            source_line=source.count('\n', 0, match.start()) + 1,
                            purpose='identity guard' if address == 8 else 'raw inherited configuration'))
    header = HERE / 'mt6762_pmic_entry.h'
    text = header.read_text()
    old = array(text, 'mt6762_pmic_entry_regs')
    assert old == [8, 0xc0c, 0xd08, 0xd0a, 0xc8e, 0xc90, 0xd94, 0xd96,
                   0xe08, 0x108a, 0x108e, 0x109e, 0x1236]
    assert array(text, 'mt6762_pmic_adc_entry_regs') == [address for _, address in ROWS]
    bif = XNU / 'bsd/dev/mt6762_bif_observer.c'
    assert array(bif.read_text(), 'bif_config_regs') == [address for _, address in ROWS[2:]]
    missing = [address for _, address in ROWS if address not in old]
    assert len(missing) == 18
    capture = PORT / 'hardware/trace-boot-20261025/capture33/xnu-log.bin'
    assert identity(capture)['sha256'] == '73275964fb858aea490204611b4de11ee019ac02a18192ec5461b0219aa3e9d4'
    log = capture.read_bytes()
    assert b'MT6762_ADC_ENTRY' not in log
    seen = {int(address, 16) for address in re.findall(rb'^MT6762_PMIC_ENTRY pass=\d+ index=\d+ address=([0-9a-f]+)', log, re.M)}
    assert all(address not in seen for address in missing)
    files = [registers, header, XNU / 'bsd/dev/mt6762_power.c', bif,
        HERE / 'test_pmic_entry.c', HERE / 'test_pmic_entry_integration.py',
        HERE / 'audit_adc_entry.py', HERE / 'evidence/ntc-compensation-bif-disassembly.txt']
    result = dict(schema='mt6762-passive-adc-entry-source-audit-v1',
        physical_new_observer_execution_proven=False,
        provenance=[identity(path) for path in files], register_catalog=catalog,
        earlier_capture=dict(**identity(capture), new_record_present=False,
                             missing_addresses=[f'{address:04x}' for address in missing]),
        format=dict(prefix='MT6762_ADC_ENTRY', version=1, passes=2,
                    registers_per_pass=19, max_additional_reads=38,
                    hardware_id_guard_first_in_each_pass=True,
                    original_prefix='MT6762_PMIC_ENTRY', original_version=1,
                    original_registers_per_pass=13, original_passes=2,
                    original_decoder_unchanged=True),
        execution=dict(read_only_pwrap_required=True, fault_free_pwrap_required=True,
                       original_two_passes_must_complete=True, stop_at_first_failure=True,
                       retries=0, partial_pass_published=False,
                       raw_words_may_differ_between_passes=True),
        grants=dict(adc_request_writes=0, latch_commands=0, trim_writes=0,
                    tdet_writes=0, pmic_writes=0, calibration_granted=False,
                    adc_owned=False, gauge_owned=False, charger_control=False,
                    measurement_valid=False),
        scope='Two sequential raw configuration observations, not an atomic measurement, fresh conversion, calibration or ownership proof.')
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: all19 ordinary ADC inventory addresses verified against BSP; original13 unchanged; capture33 remains historical; no device access')


if __name__ == '__main__':
    main()
