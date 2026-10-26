#!/usr/bin/env python3
"""Offline I2C5 handoff evidence and proposed passive register inventory.

Reads retained capture/source files only. Never imports a device interface,
performs MMIO, changes a handoff grant, or writes an existing output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=Path, required=True)
    p.add_argument('--bsp', type=Path, required=True)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    xnu = a.port / 'xnu'
    raw = (a.capture / 'peripherals.bin').read_bytes()
    decoded = json.loads((a.capture / 'peripherals-result.json').read_text())
    if (len(raw) != 4096 or raw[:8] != b'MTKPER01' or
            struct.unpack_from('<II', raw, 8) != (1, 4096) or
            struct.unpack_from('<4I', raw, 48) != (2, 0xfffffffd, 2, 186) or
            digest(a.capture / 'peripherals.bin') != decoded['sha256'] or
            len(decoded['registers']) != 187):
        raise ValueError('Require completed original187-entry peripheral capture')
    observed = {}
    for i, e in enumerate(decoded['registers']):
        actual = struct.unpack_from('<IBBHII', raw, 96 + 16 * i)
        expected = (int(e['address'], 16), e['width'], e['group'],
                    e['valid'], e['first'], e['second'])
        if actual != expected or actual[0] in observed:
            raise ValueError('Decoded capture differs from raw record')
        observed[actual[0]] = e

    sources = {
        'stock_dt': ('port', 'firmware/boot.dts'),
        'stock_dtb': ('port', 'firmware/boot.bin.dtb'),
        'pin_fields': ('bsp', 'kernel-4.14/drivers/pinctrl/mediatek/pinctrl-mt6765.c'),
        'pin_functions': ('bsp', 'kernel-4.14/include/dt-bindings/pinctrl/mt6765-pinfunc.h'),
        'i2c_registers': ('bsp', 'kernel-4.14/drivers/i2c/busses/i2c-mtk.h'),
        'i2c_driver': ('bsp', 'kernel-4.14/drivers/i2c/busses/i2c-mtk.c'),
        'native_platform': ('port', 'xnu/bsd/dev/mt6762_platform.c'),
        'native_power': ('port', 'xnu/bsd/dev/mt6762_power.c'),
        'native_charger': ('port', 'xnu/bsd/dev/mt6762_charger_protocol.h'),
        'capture_definition': ('port', 'xnu/tools/mt6762/physical/peripheral_probe.h'),
        'fallback_audit': ('port', 'xnu/tools/mt6762/hardware/power/evidence/bif-fallback-audit.json'),
        'manufacturer_source': ('port', 'xnu/tools/mt6762/hardware/power/evidence/datasheet-source.json'),
    }
    pins = {key: {'root': root, 'path': path,
                  'sha256': digest((a.port if root == 'port' else a.bsp) / path)}
            for key, (root, path) in sources.items()}
    entries = []

    def add(address, width, group, name, source, detail):
        if address in observed or any(int(e['address'], 16) == address for e in entries):
            raise ValueError('Duplicate or already captured address')
        entries.append(dict(address=f'0x{address:08x}', width=width, group=group,
                            name=name, source=source, detail=detail))

    add(0x10005360, 4, 0, 'GPIO I2C5 MODE', 'pin_fields:34;pin_functions:410,414',
        'GPIO48/49 low nibbles: function1 for SCL5/SDA5 corresponds to mask0xff/value0x11. Active value unmeasured.')
    add(0x10005010, 4, 0, 'GPIO I2C5 DIR', 'pin_fields:53',
        'Direction bits16/17; capture before selecting a physical profile.')
    add(0x10005210, 4, 0, 'GPIO I2C5 DIN', 'pin_fields:62',
        'Input levels bits16/17; idle line levels unmeasured. No pin/output write.')
    for address, name, source, detail in [
        (0x10002610, 'DRIVE', 'pin_fields:894,895', 'Shared three-bit field18..20.'),
        (0x10002650, 'IES', 'pin_fields:129,130', 'Input-enable bits3/5.'),
        (0x10002670, 'PD', 'pin_fields:635,636', 'Pull-down bits3/5.'),
        (0x10002690, 'PU', 'pin_fields:481,482', 'Pull-up bits3/5.'),
    ]:
        add(address, 4, 0, 'IOCFG_BL I2C5 ' + name, source,
            detail + ' Base4 is0x10002600 in stock_dt:748-750. Capture only.')
    for offset, name in [(0x114, 'ISENABLER5'), (0x214, 'ISPENDR5'), (0x314, 'ISACTIVER5')]:
        add(0x0c000000 + offset, 4, 0, 'GICD I2C5 ' + name,
            'stock_dt:2780;native_platform:initialize_bus',
            'INTID162 = SPI130 +32, bit2. Ordinary read; no acknowledge. Pending need not be cleared; enable/active require review before ownership.')
    for offset, name in [
        (4, 'SLAVE_ADDR'), (8, 'INTR_MASK'), (12, 'INTR_STAT'), (16, 'CONTROL'),
        (20, 'TRANSFER_LEN'), (24, 'TRANSAC_LEN'), (28, 'DELAY_LEN'), (32, 'TIMING'),
        (36, 'START'), (40, 'EXT_CONF'), (44, 'LTIMING'), (48, 'HS'), (52, 'IO_CONFIG'),
        (68, 'TRANSFER_LEN_AUX'), (72, 'CLOCK_DIV'), (76, 'HW_TIMEOUT'),
    ]:
        add(0x11016000 + offset, 2, 2, 'I2C5 ' + name,
            'i2c_registers:230-252;i2c_driver:663-724',
            'V2 config/status read; group2 requires shared I2C clocks. START is observed only. INTR_STAT uses a separate acknowledge write in i2c_driver:460-461; no write here.')
    for offset, name in [
        (0, 'INT_FLAG'), (4, 'INT_EN'), (8, 'EN'), (24, 'CON'), (28, 'TX_MEM_ADDR'),
        (32, 'RX_MEM_ADDR'), (36, 'TX_LEN'), (40, 'RX_LEN'),
        (84, 'TX_MEM_ADDR2'), (88, 'RX_MEM_ADDR2'),
    ]:
        add(0x11000580 + offset, 4, 3, 'APDMA5 ' + name,
            'stock_dt:2778;i2c_registers:124-139;i2c_driver:690-738',
            'Config/status read; group3 additionally requires APDMA gate. Address words are recorded only, never dereferenced. No DMA command or acknowledge.')
    if len(entries) != 36 or 187 + 12 + len(entries) > 250:
        raise ValueError('Unexpected passive register budget')
    common = []
    for address in (0x100000a0, 0x10001090, 0x10001094, 0x1000c26c,
                    0x1000c270, 0x1000c278, 0x100026c0):
        e = observed[address]
        if e['valid'] != 3 or e['first'] != e['second']:
            raise ValueError('Shared clocks/pad observation is not stable')
        common.append(dict(address=e['address'], name=e['name'], value=hex(e['first']),
                           stable=True, already_present=True))
    log = (a.capture / 'dram-log-complete.bin').read_bytes()
    patterns = [b'psc5425', b'charger', b'bq24158', b'eta6947']
    result = dict(
        format='mt6762-i2c5-passive-review-1',
        purpose='Additional passive capture for PSC5425E handoff review; no ownership grant or charger operation',
        device_access=False, charge_enable=False, ownership_established=False,
        sources=pins,
        capture=dict(name=a.capture.name, peripheral_raw_sha256=digest(a.capture / 'peripherals.bin'),
                     decoded_sha256=digest(a.capture / 'peripherals-result.json'),
                     all187_records_matched_to_raw=True, shared_observations=common,
                     i2c5_controller_dma_irq_gpio_records_present=0,
                     shared_parent_index=2, shared_parent_hz=124800000,
                     rate_scope='Existing native parent decode and bus0 capture; not measured I2C5 frequency',
                     existing_smt_detail='IOCFG_BL+0xc0=0x3c000; GPIO48/49 SMT bits15/17 are both set',
                     lk_log_sha256=hashlib.sha256(log).hexdigest(), lk_log_bytes=len(log),
                     lk_patterns_searched=[v.decode() for v in patterns],
                     lk_pattern_matches=[v.decode() for v in patterns if v in log.lower()],
                     lk_negative_scope='This retained span only; no conclusion that LK never touches the charger'),
        new_passive_registers=entries,
        entry_budget=dict(existing=187, parent_cpu_additions=12, new_i2c5=36,
                          total=235, capacity=250, remaining=15),
        exclusions=[
            'DATA_PORT/FIFO reads, FIFO clear, SOFTRESET, MCU event/command, DMA reset/start/stop/ack writes.',
            '0x10002620/0x100026b0: DT enhanced-drive/resistor-selection offsets lack exact4.19 field reconciliation in this review.',
            'No PSC5425E or display-bias device transactions. No captured address pointer is followed.',
        ],
        integration_findings=[
            'Physical producer currently has no measured i2c5-verified ownership profile; shared gate/PLL values alone are insufficient.',
            'initialize_bus selects inherited DIV/HS profile only for id0 && touch-inherited-probe. Bus5 still uses laboratory expectations; measure bus5 rather than copying bus0 assumptions.',
            'mt6762_power_init returns from pwrap-inherited-probe after keys setup, before charger initialization. Adding charger flags alone cannot activate this path.',
            'PSC read-modify-write helper requires caller-exclusive control across the entire sequence. Controller-idle alone is not a transfer of all prior users.',
            'Existing physical desktop has no charger-control handoff or verified independent disable fallback; autonomous charging remains unproved.',
        ],
        next_sequence=[
            'Append these36 entries to a new build-bound passive record/decoder. Keep installed Image30/capture23 identity unchanged. Clocks precede group2/3; retain two passes without granting ownership.',
            'Use measured values to define an I2C5 entry profile: shared clocks, GPIO48/49, pads, masked/inactive INTID162, START/IRQ/APDMA idle. Recheck before setup; no guessed reset or clock reparenting.',
            'Add a separate read-only-charger probe compatible with PWRAP/keys. Require all programmed controller readbacks, including measured bus5 DIV/HS and AUX configuration.',
            'Read fixed address0x6a register3 via one-byte address write/repeated-START one-byte read. Require ID0xf0, then read control1/status0. No scanning or access to bias address0x3e.',
            'After bus/ID/control proof and exclusive ownership, use mt6762_psc_disable_owned: reject OPA_MODE, write only Reg1 bit2 if needed, require exact before|4 readback. No charge-enable, voltage/current or reset writes.',
            'Resolve CE failure/VBUS-POR behavior before a long physical desktop trial. Register readback alone does not establish an independent hardware fallback or battery-temperature protection.',
        ],
        manufacturer_scope=dict(
            metadata='sources.manufacturer_source', fallback_evidence='sources.fallback_audit',
            facts=['Reg1 bit2 is active-low charge enable.',
                   'The existing manufacturer audit identifies the32-second watchdog as OTG-specific.',
                   'Stock GPIO42 is named interrupt; supported disable GPIO wiring is not established.'],
            limits='No new analog resistor/cell/NTC calibration and no charge-enable implementation.'),
    )
    # Sources may be read while another task builds; never publish mixed pins.
    for key, (root, path) in sources.items():
        if digest((a.port if root == 'port' else a.bsp) / path) != pins[key]['sha256']:
            raise ValueError('Source changed during audit: ' + key)
    with a.output.open('x') as f:
        f.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(output=str(a.output), new_registers=36, total_with_cpu12=235,
                          capture_raw_verified=True, device_access=False)))


if __name__ == '__main__':
    main()
