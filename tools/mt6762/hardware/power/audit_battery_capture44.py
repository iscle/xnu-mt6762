"""Retain bounded read-only capture44 battery evidence; no device access."""
from pathlib import Path
import hashlib
import json
import re
import struct

HERE = Path(__file__).resolve().parent
XNU = HERE.parents[3]
PORT = XNU.parents[2]
CAPTURE = PORT / 'hardware/trace-boot-20261025/capture44'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def properties(data):
    """Decode this retained, complete DT; not a hardware admission parser."""
    h = struct.unpack_from('>10I', data)
    assert h[0] == 0xd00dfeed and h[1] == len(data)
    offset, end, strings, stack = h[2], h[2] + h[9], h[3], []
    out = {}
    while offset < end:
        token = struct.unpack_from('>I', data, offset)[0]
        offset += 4
        if token == 1:
            stop = data.index(0, offset, end)
            stack.append(data[offset:stop].decode())
            offset = (stop + 4) & ~3
        elif token == 2:
            assert stack
            stack.pop()
        elif token == 3:
            length, name_offset = struct.unpack_from('>II', data, offset)
            offset += 8
            assert strings <= strings + name_offset < strings + h[8]
            name = data[strings + name_offset:data.index(0, strings + name_offset, strings + h[8])].decode()
            assert offset + length <= end
            key = '/'.join(stack), name
            assert key not in out
            out[key] = data[offset:offset + length]
            offset = (offset + length + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            assert not stack
            return out
        else:
            raise ValueError(token)
    raise ValueError('missing FDT end')


def main():
    log = (CAPTURE / 'xnu-log-ordered.bin').read_bytes()
    assert sha(log) == '4eb9b9fb33eca61b4e852a257ac17160e117646c6e6140711fca13fd51279f2d'
    text = log.decode(errors='replace')
    d = (CAPTURE / 'runtime.dtb').read_bytes()
    dt = properties(d)
    gauge = '/pwrap@1000d000/main_pmic/mtk_gauge'
    selected = {}
    for (path, name), value in dt.items():
        if path == gauge and re.search('(?i)profile|q_max|qmax|temperature_t|saddles|multi_battery|pull_up|com_fg|com_r_fg|temp_compensate|battery_id', name):
            assert len(value) % 4 == 0
            selected[name] = {'bytes': len(value), 'sha256': sha(value),
                              'cells_be32': list(struct.unpack('>' + str(len(value) // 4) + 'I', value))}
    wanted = ('MT6762_PSC_PROBE ', 'MT6762_PMIC_ENTRY ', 'MT6762_ADC_ENTRY ',
              'MT6762_BAT_COUNT ', 'MT6762_BAT_SYSCTL ')
    retained = [line for line in text.splitlines() if line.startswith(wanted)]
    counts = [int(line.rsplit(' ', 1)[1]) for line in retained if line.startswith('MT6762_BAT_COUNT ')]
    assert counts == [0] * 12
    psc = [line for line in retained if line.startswith('MT6762_PSC_PROBE ')]
    assert len(psc) == 2 and all('error=0 id=f0 control=f8 status=10' in line for line in psc)
    manifest = PORT / 'boot/physical-xnu-build47/physical-manifest.json'
    evidence = {
        'schema': 'mt6762-battery-capture44-observer-v1',
        'input': {str(p): sha(p.read_bytes()) for p in [CAPTURE / 'xnu-log-ordered.bin', CAPTURE / 'runtime.dtb', manifest]},
        'observed': {'psc_id': 240, 'control': 248, 'status': 16, 'iops_counts': counts,
                     'adc_conversion_proven': False, 'measured_current_proven': False,
                     'remaining_capacity_proven': False},
        'interpretation': {'psc_state': 'charging', 'CE_disabled': False,
                           'transport_failure': False, 'battery_observer_enabled_in_capture': False,
                           'physical_charge_current_not_measured': True},
        'lines': retained,
        'selected_live_gauge_dt_properties': selected,
        'chosen_loader_strings': {name: value.decode() for (path, name), value in dt.items()
                                  if path == '/chosen' and name.startswith('atag,fg_')},
        'scope': 'Retained physical capture plus current source; new observer physical execution not established by this audit.',
        'soc_boundary': 'num=100/col=3 but 74 triplets in each table; exact shipped parser semantics, profile selection and fresh paired measurements remain to establish.',
        'source_sha256': {name: sha((XNU / name).read_bytes()) for name in [
            'bsd/dev/mt6762_power.c', 'bsd/dev/mt6762_battery_observer.c', 'bsd/dev/mt6762_gauge.c',
            'bsd/dev/mt6762_gauge_latch_probe.c', 'bsd/dev/mt6762_gauge_protocol.h',
            'bsd/dev/hakios.battery.c', 'iokit/Kernel/hakios.battery.cpp']},
        'validation': {'command': 'sh tools/mt6762/hardware/power/test.sh', 'result': 'PASS',
                       'observer_wacs_failure_cases': 272, 'observer_config_mutations': 16,
                       'observer_expiry_positions': 70,
                       'includes_actual_gauge_getter_bridge': True,
                       'includes_parent_repeated_psc_policy': True}}
    output = HERE / 'evidence/battery-capture44-observer.json'
    output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'{output}: sha256={sha(output.read_bytes())}')


if __name__ == '__main__':
    main()
