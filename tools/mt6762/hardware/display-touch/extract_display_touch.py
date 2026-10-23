#!/usr/bin/env python3
"""Extract board-specific display/touch facts from this stock symbolized ELF.

Read-only input. Addresses are tied to the exact stock Image SHA256 below;
this is deliberately not a heuristic extractor for other firmware revisions.
The optional touch firmware blob stays local and is never installed/flashed.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

IMAGE_SHA256 = "82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b"
BASE = 0xffffff8008080000


class ELF:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if self.data[:6] != b"\x7fELF\x02\x01":
            raise ValueError("expected ELF64 little endian")
        if struct.unpack_from("<H", self.data, 18)[0] != 183:
            raise ValueError("expected AArch64")
        off = struct.unpack_from("<Q", self.data, 32)[0]
        size, count = struct.unpack_from("<HH", self.data, 54)
        self.loads = []
        for i in range(count):
            typ, flags, poff, va, pa, filesz, memsz, align = struct.unpack_from(
                "<IIQQQQQQ", self.data, off + i * size)
            if typ == 1:
                if poff + filesz > len(self.data) or filesz > memsz:
                    raise ValueError("invalid load segment")
                self.loads.append((va, poff, filesz))
        image = next((self.data[o:o+n] for a, o, n in self.loads if a == BASE), None)
        if image is None or hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
            raise ValueError("stock Image hash does not match fixed address map")

    def read(self, address, size):
        for base, offset, length in self.loads:
            if base <= address and address + size <= base + length:
                return self.data[offset + address-base:offset + address-base+size]
        raise ValueError(f"unbacked address {address:#x}+{size:#x}")

    def table(self, address, count):
        result = []
        for i in range(count):
            a = address + i * 72
            b = self.read(a, 72)
            cmd, n = struct.unpack_from("<IB", b)
            if cmd == 0xffe:
                entry = {"delay_ms": n}
            elif cmd == 0xfff:
                entry = {"end": True}
            elif cmd <= 255 and n <= 64:
                entry = {"dcs_command": cmd, "parameters": b[5:5+n].hex(), "force_update": True}
            else:
                raise ValueError("unexpected LCM entry")
            result.append({"stock_va": hex(a), **entry})
        return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("elf", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--extract-touch-firmware", action="store_true")
    args = ap.parse_args()
    elf = ELF(args.elf)
    args.output.mkdir(parents=True, exist_ok=True)
    fw = elf.read(0xffffff80090e0ce9, 50192)
    display_clocks = []
    for i in range(25):
        _, name, refs, membership, module = struct.unpack_from("<QQIII", elf.read(0xffffff800983f658+32*i, 32))
        display_clocks.append({"index":i, "name":elf.read(name,64).split(b"\0")[0].decode(),
                               "initial_refs":refs,"display_membership":membership,"module_id":module})
    facts = {
        "source_image_sha256": IMAGE_SHA256,
        "source_elf_sha256": hashlib.sha256(elf.data).hexdigest(),
        "method": "bounded ELF extraction; instruction-level evidence in sibling .asm files; no native REA provider configured",
        "panel": {
            "driver": "axs15260_dsi_6580_hd", "width": 384, "height": 854,
            "parameter_function_va": "0xffffff800874771c",
            "mode": "SYNC_EVENT_VDO_MODE", "lanes": 3,
            "data_format_raw": [0,3,0,0], "packet_stream_selector": 2,
            "rgb_format_inference": "24-bit RGB888 from PS selector2; stock data_format enum3 differs from provided BSP enum and needs exact-stock DSI confirmation",
            "pll_clock_mhz": 210,
            "vertical": {"sync": 2, "back_porch": 20, "front_porch": 170, "active": 854},
            "horizontal": {"sync": 20, "back_porch": 180, "front_porch": 180, "active": 384},
            "reset_sequence": [{"level":1,"delay_ms":20},{"level":0,"delay_ms":20},{"level":1,"delay_ms":100}],
            "init": elf.table(0xffffff800983e9f8, 8),
            "suspend": elf.table(0xffffff800983ec38, 5),
            "proximity_resume": elf.table(0xffffff800983eda0, 5),
            "id": {"commands": [0xda, 0xdb, 0xdc], "expected_bytes": "005260", "stock_va": "0xffffff8008747928"},
            "bias": {"slave_address": 0x3e, "register_writes": [[0,0x12],[1,0x12]], "stock_va": "0xffffff8008747ae8"},
        },
        "touch": {
            "i2c_bus": 0, "i2c_mmio": "0x11007000", "slave_address": 0x3b,
            "address_override_va": "0xffffff8008a25efc",
            "packet_read": "single 32-byte I2C read; no register prefix",
            "packet_length_va": "0xffffff8008a26610",
            "packet_parse_va": "0xffffff8008a26db4",
            "contacts_max": 5, "record_offset": 2, "record_stride": 6,
            "header": "byte0=0; byte1 high nibble=0; byte1 low nibble count clamped to5; id>=5 ends records",
            "record": {"x":"((b0&15)<<8)|b1", "y":"((b2&15)<<8)|b3", "event":"b0>>6", "id":"b2>>4", "pressure":"b4", "area":"b5>>4"},
            "event": {"0":"down", "1":"up", "2":"contact", "3":"not reported active"},
            "zero_contact_packet": "release all active contacts",
            "version_read": {"write_hex":"0c", "read_bytes":2, "byte_order":"big", "stock_va":"0xffffff8008a25ac4"},
            "reset_sequence": [{"level":1,"delay_us_min":1000,"delay_us_max":1100},{"level":0,"delay_us_min":10000,"delay_us_max":11000},{"level":1,"delay_ms":20}],
            "irq_flags": "IRQF_ONESHOT | IRQF_TRIGGER_FALLING (0x2002)",
            "firmware": {"stock_va":"0xffffff80090e0ce9", "length":len(fw), "sha256":hashlib.sha256(fw).hexdigest(), "version_bytes_at_0x7634":fw[0x7634:0x7636].hex(), "upgrade":"flash init/erase/write/read-check, not RAM-only; not performed by these tools"},
        },
        "dt_candidates_not_live_verified": {
            "panel_reset_gpio":45, "panel_bias_enable_gpio":150,
            "panel_bias_i2c_bus":5, "panel_bias_i2c_mmio":"0x11016000",
            "touch_reset_gpio":174,"touch_interrupt_gpio":0,
            "touch_supply":"MT6357 vldo28",
            "caution":"stock DT overlay contains stale panel identity/resolution; pin mappings require LK final-DT or physical confirmation",
        },
        "brightness": {
            "mode_evidence":"static DT overlay led@6 led_mode5; provided BSP maps5 to MT65XX_LED_MODE_CUST_BLS_PWM",
            "pwm_mmio":"0x1100e000", "pwm_mmio_source":"stock boot DT disp_pwm@1100e000",
            "stock_maximum":struct.unpack("<I",elf.read(0xffffff80098423f4,4))[0],
            "stock_set_function":"0xffffff80087f9250",
            "stock_direct_write_vas":["0xffffff80087f9550","0xffffff80087f9658","0xffffff80087f97d0"],
            "register_offsets":{"enable":"0x00","commit":"0x0c","divider":"0x18","period_and_duty":"0x1c"},
            "register_fields":{"enable":"bit0", "divider":"bits25:16", "period":"bits9:0=1023", "duty":"bits28:16"},
            "zero_brightness":"write duty1, clear enable bit0; commit1 then0",
            "nonzero_brightness":"clamp0..maximum, write duty, set enable bit0; commit1 then0",
            "dt_pwm_config":{"clock_source_request":0,"divider":3},
            "pwm_source_request_to_parent":{"0":"ULPOSC1_D8","1":"ULPOSC1_D2","2":"UNIVPLL2_D4","3":"26MHz"},
            "pwm_hardware_mux_encoding_to_parent":{"0":"26MHz","1":"UNIVPLL2_D4","2":"ULPOSC1_D2","3":"ULPOSC1_D8"},
            "clock_mapping_source":"provided BSP kernel-4.14 drivers/misc/mediatek/video/mt6765/dispsys/ddp_pwm_mux.c and drivers/clk/mediatek/clk-mt6765.c; not live verified",
            "limits":["No physical brightness writes or register reads performed", "Exported Android brightness does not reveal PWM duty/clock state", "PWM output pin and external backlight IC identity remain unverified", "Clock/rail/pin ownership must precede native register access"],
        },
        "display_clock_table":{"stock_va":"0xffffff800983f658","entry_stride":32,"entries":display_clocks},
        "historical_handoff_not_current": {
            "framebuffer_base":"0x7ef90000", "reservation_size":"0x470000",
            "advertised_vram_size":4653056, "fps_raw":6184,
            "source":"retained expdb LK boot logs; no live register or scanout-format verification",
        },
        "unknown": ["live panel scanout physical address/stride/pixel format", "LK final DT pin and regulator overrides", "AXS current flash version and reason both old boots reflash", "physical I2C transfer and interrupt behavior"],
    }
    (args.output / "facts.json").write_text(json.dumps(facts, indent=2)+"\n")
    if args.extract_touch_firmware:
        (args.output / "axs-firmware.bin").write_bytes(fw)
    print(json.dumps({"facts":str(args.output / "facts.json"),"touch_firmware_sha256":facts["touch"]["firmware"]["sha256"]}))


if __name__ == "__main__":
    main()
