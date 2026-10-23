"""Host-side validation of the Mach-O loader's trust boundaries and boot ABI."""
import ctypes
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import prepare as p


def fixture():
    image = bytearray(4096)
    struct.pack_into('<8I', image, 0, 0xfeedfacf, 0x100000c, 0, 2, 2, 360, 0, 0)
    struct.pack_into('<II16s4Q4I', image, 32, 25, 72, b'__TEXT', p.VIRT + 0x3004000,
                     0x4000, 0, 4096, 5, 5, 0, 0)
    struct.pack_into('<4I', image, 104, 5, 288, 6, 68)
    struct.pack_into('<Q', image, 104 + 16 + 32 * 8, p.VIRT + 0x3004200)
    return image


def parse_adt(data, off=0):
    props, children = struct.unpack_from('<II', data, off)
    off += 8
    result = {}
    for _ in range(props):
        name, length = struct.unpack_from('<32sI', data, off)
        off += 36
        value = data[off:off + length]
        if len(value) != length:
            raise ValueError('truncated ADT property')
        result[name.rstrip(b'\0').decode()] = value
        off += (length + 3) & ~3
    result['children'] = []
    for _ in range(children):
        child, off = parse_adt(data, off)
        result['children'].append(child)
    return result, off


class BootVideo(ctypes.LittleEndianStructure):
    _fields_ = [(name, ctypes.c_uint64) for name in ('base', 'display', 'rowBytes', 'width', 'height', 'depth')]


class TopologyTests(unittest.TestCase):
    def test_eight_a53_affinities_and_single_boot_cpu(self):
        tree, _ = parse_adt(p.make_adt(bytes(64), cpus=8))
        cpus = next(n for n in tree['children'] if n['name'] == b'cpus\0')['children']
        self.assertEqual([struct.unpack('<I', n['reg'])[0] for n in cpus],
                         [0, 1, 2, 3, 0x100, 0x101, 0x102, 0x103])
        self.assertEqual([n['state'] for n in cpus], [b'running\0'] + [b'stopped\0']*7)
        self.assertEqual([struct.unpack('<I', n['cluster-id'])[0] for n in cpus], [0]*4 + [1]*4)
        for count in (0, 9):
            with self.assertRaises(ValueError): p.make_adt(bytes(64), cpus=count)


class BootArgs(ctypes.LittleEndianStructure):
    _fields_ = [('revision', ctypes.c_uint16), ('version', ctypes.c_uint16),
                ('virtBase', ctypes.c_uint64), ('physBase', ctypes.c_uint64),
                ('memSize', ctypes.c_uint64), ('topOfKernelData', ctypes.c_uint64),
                ('video', BootVideo), ('machineType', ctypes.c_uint32),
                ('deviceTreeP', ctypes.c_uint64), ('deviceTreeLength', ctypes.c_uint32),
                ('commandLine', ctypes.c_char * 608), ('bootFlags', ctypes.c_uint64),
                ('memSizeActual', ctypes.c_uint64)]


class PrepareTests(unittest.TestCase):
    def test_power_handoff_is_explicit_and_does_not_grant_charge_enable(self):
        for enabled in (False, True):
            tree, _ = parse_adt(p.make_adt(bytes(64), native_lab_i2c=True, native_lab_power=enabled))
            chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
            handoff = next(n for n in chosen['children'] if n['name'] == b'mt6762-handoff\0')
            for name in ('pwrap-verified', 'adc-verified', 'keypad-verified'):
                if enabled:
                    self.assertEqual(struct.unpack('<I', handoff[name])[0], 1)
                else:
                    self.assertNotIn(name, handoff)
            for name in ('charger-enable', 'battery-calibrated', 'sspm-mailbox-owned', 'display-verified'):
                self.assertNotIn(name, handoff)
        with self.assertRaises(ValueError):
            p.make_adt(bytes(64), native_lab_power=True)

    def test_native_display_handoff_uses_reserved_buffer(self):
        fb = dict(addr=0x48000000, size=0x144000)
        tree, _ = parse_adt(p.make_adt(bytes(64), framebuffer=True,
                           native_lab_i2c=True, native_lab_display=fb))
        chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
        handoff = next(n for n in chosen['children'] if n['name'] == b'mt6762-handoff\0')
        self.assertEqual(struct.unpack('<Q', handoff['fb-phys'])[0], fb['addr'])
        self.assertEqual(handoff['fb-reserved-base'], handoff['fb-phys'])
        self.assertEqual(struct.unpack('<Q', handoff['fb-size'])[0], fb['size'])
        self.assertEqual(struct.unpack('<I', handoff['brightness-verified'])[0], 1)
        for bad in [dict(addr=0x48000001, size=0x144000), dict(addr=0xffff0000, size=0x144000)]:
            with self.assertRaises(ValueError):
                p.make_adt(bytes(64), framebuffer=True, native_lab_i2c=True, native_lab_display=bad)
        with self.assertRaises(ValueError):
            p.make_adt(bytes(64), native_lab_display=fb)

    def test_sspm_handoff_is_explicit(self):
        tree, _ = parse_adt(p.make_adt(bytes(64), native_lab_i2c=True, native_lab_sspm=True))
        chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
        handoff = next(n for n in chosen['children'] if n['name'] == b'mt6762-handoff\0')
        self.assertEqual(struct.unpack('<I', handoff['sspm-mailbox-owned'])[0], 1)
        with self.assertRaises(ValueError): p.make_adt(bytes(64), native_lab_sspm=True)

    def test_thermal_handoff_requires_power(self):
        tree, _ = parse_adt(p.make_adt(bytes(64), native_lab_i2c=True,
                           native_lab_power=True, native_lab_thermal=True))
        chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
        handoff = next(n for n in chosen['children'] if n['name'] == b'mt6762-handoff\0')
        self.assertEqual(struct.unpack('<I', handoff['pmic-thermal-adc-owned'])[0], 1)
        self.assertNotIn('cpu-thermal-owned', handoff)
        with self.assertRaises(ValueError): p.make_adt(bytes(64), native_lab_thermal=True)

    def test_gauge_handoff_matches_synthetic_fixture(self):
        tree, _ = parse_adt(p.make_adt(bytes(64), native_lab_i2c=True,
                           native_lab_power=True, native_lab_gauge=True))
        chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
        handoff = next(n for n in chosen['children'] if n['name'] == b'mt6762-handoff\0')
        for key,value in {'fgauge-owned':1, 'fgauge-calibration-verified':1, 'fgauge-rfg':100,
                'fgauge-car-tune':1000, 'fgauge-con0':0x29, 'fgauge-gain':4096}.items():
            self.assertEqual(struct.unpack('<I', handoff[key])[0],value)
        with self.assertRaises(ValueError): p.make_adt(bytes(64), native_lab_gauge=True)

    def test_msdc_handoff_is_independent_and_capacity_is_explicit(self):
        tree,_=parse_adt(p.make_adt(bytes(64),native_lab_msdc_sectors=128))
        chosen=next(n for n in tree['children'] if n['name']==b'chosen\0')
        handoff=next(n for n in chosen['children'] if n['name']==b'mt6762-handoff\0')
        for key,value in {'lab-fixture':1,'msdc-owned':1,'msdc-inherited-verified':1,
                          'msdc-sector-count':128,'msdc-rca':1,'msdc-cfg':0x89,
                          'msdc-sdc-cfg':0x20000,'msdc-timeout-us':10000,
                          'msdc-card-clock-hz':200000000}.items():
            self.assertEqual(struct.unpack('<I',handoff[key])[0],value)
        self.assertNotIn('i2c0-verified',handoff)
        self.assertNotIn('touch-verified',handoff)
        for sectors in [-1,0x100000000]:
            with self.assertRaises(ValueError):p.make_adt(bytes(64),native_lab_msdc_sectors=sectors)

    def test_msdc_file_metadata_never_rewrites_source(self):
        with tempfile.TemporaryDirectory() as d:
            image=Path(d)/'fixture.raw';original=bytes(range(256))*4;image.write_bytes(original)
            metadata=p.msdc_image_metadata(image)
            self.assertEqual(metadata['sector_count'],2)
            self.assertTrue(metadata['readonly'])
            self.assertEqual(image.read_bytes(),original)
            image.write_bytes(b'bad')
            with self.assertRaises(ValueError):p.msdc_image_metadata(image)
            with self.assertRaises(ValueError):p.msdc_image_metadata(Path(d))

    def test_publication_gap_requires_explicit_power_lab_and_bounds(self):
        tree,_=parse_adt(p.make_adt(bytes(64),native_lab_i2c=True,
            native_lab_power=True,native_lab_battery_gap_start_ms=60000,
            native_lab_battery_gap_ms=8000))
        chosen=next(n for n in tree['children'] if n['name']==b'chosen\0')
        handoff=next(n for n in chosen['children'] if n['name']==b'mt6762-handoff\0')
        self.assertEqual(struct.unpack('<I',handoff['lab-fixture'])[0],1)
        self.assertEqual(struct.unpack('<I',handoff['battery-report-gap-start-ms'])[0],60000)
        self.assertEqual(struct.unpack('<I',handoff['battery-report-gap-ms'])[0],8000)
        for start,duration in [(0,2000),(1000,0),(999,2000),(300001,2000),(1000,1999),(1000,10001)]:
            with self.assertRaises(ValueError):
                p.make_adt(bytes(64),native_lab_i2c=True,native_lab_power=True,
                    native_lab_battery_gap_start_ms=start,native_lab_battery_gap_ms=duration)
        with self.assertRaises(ValueError):
            p.make_adt(bytes(64),native_lab_battery_gap_start_ms=1000,native_lab_battery_gap_ms=2000)
        normal,_=parse_adt(p.make_adt(bytes(64),native_lab_i2c=True,native_lab_power=True))
        chosen=next(n for n in normal['children'] if n['name']==b'chosen\0')
        handoff=next(n for n in chosen['children'] if n['name']==b'mt6762-handoff\0')
        self.assertNotIn('battery-report-gap-ms',handoff)

    def test_bif_handoff_is_explicit_and_readonly_tdet(self):
        tree, _ = parse_adt(p.make_adt(bytes(64), native_lab_i2c=True,
                           native_lab_power=True, native_lab_bif=True))
        chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
        handoff = next(n for n in chosen['children'] if n['name'] == b'mt6762-handoff\0')
        for key,value in {'bif-adc-owned':1, 'baton-tdet-owned':1, 'bif-trim-verified':1,
                'bif-tdet':4, 'bif-sw-gain-trim':0x4000, 'bif-sw-offset-trim':0}.items():
            self.assertEqual(struct.unpack('<I', handoff[key])[0],value)
        for n in (0,1,2,5,7,9,11,12):
            self.assertEqual(struct.unpack('<I', handoff['bif-adc-con'+str(n)])[0],0)
        with self.assertRaises(ValueError): p.make_adt(bytes(64), native_lab_bif=True)

    def test_valid_macho(self):
        m = p.parse_macho(fixture())
        self.assertEqual(m['entry'], p.VIRT + 0x3004200)
        self.assertEqual(m['segments'][0]['filesize'], 4096)

    def test_reject_bad_commands_and_entry(self):
        for offset, value in [(36, 0), (36, 4096), (104 + 8, 1), (104 + 12, 0), (8, 2)]:
            with self.subTest(offset=offset, value=value):
                image = fixture()
                struct.pack_into('<I', image, offset, value)
                with self.assertRaises(ValueError):
                    p.parse_macho(image)
        image = fixture()
        struct.pack_into('<Q', image, 104 + 16 + 32 * 8, p.VIRT + 0x4000000)
        with self.assertRaises(ValueError):
            p.parse_macho(image)

    def test_file_bounds(self):
        with self.assertRaises(ValueError):
            p.parse_macho(fixture()[:500])
        image = fixture()
        struct.pack_into('<Q', image, 32 + 56, 0x5000)
        with self.assertRaises(ValueError):
            p.parse_macho(image)

    def test_physical_bounds_and_overlap(self):
        one = dict(name='one', addr=p.PHYS + 0x1000, size=0x1000)
        p.validate_regions([one, dict(name='two', addr=p.PHYS + 0x2000, size=0x1000)])
        for other in [dict(name='overlap', addr=p.PHYS + 0x1fff, size=1),
                      dict(name='outside', addr=p.PHYS - 1, size=1),
                      dict(name='outside', addr=p.PHYS + p.MEMORY, size=1)]:
            with self.assertRaises(ValueError):
                p.validate_regions([one, other])

    def test_boot_abi(self):
        self.assertEqual(ctypes.sizeof(BootArgs), 736)
        args = BootArgs.from_buffer_copy(p.boot_args(0x44000000, 12345, 0x44008000, 'cpus=1'))
        self.assertEqual(args.deviceTreeP, p.VIRT + 0x4000000)
        self.assertEqual(args.commandLine, b'cpus=1')
        self.assertEqual(args.topOfKernelData, 0x44008000)
        self.assertEqual(args.memSizeActual, p.MEMORY)
        self.assertEqual(args.video.base, 0)
        with self.assertRaises(ValueError):
            p.boot_args(0, 0, 0, 'x' * 608)

    def test_adt_and_nvram(self):
        adt = p.make_adt(bytes(range(64)))
        tree, consumed = parse_adt(adt)
        self.assertEqual(consumed, len(adt))
        nodes = {n['name'].rstrip(b'\0'): n for n in tree['children']}
        chosen = nodes[b'chosen']
        self.assertEqual(chosen['random-seed'], bytes(range(64)))
        self.assertEqual(chosen['dram-base'], struct.pack('<Q', p.PHYS))
        bank = chosen['nvram-proxy-data']
        self.assertEqual(len(bank), 8192)
        self.assertEqual(struct.unpack_from('<I', bank, 16)[0], zlib.adler32(bank[20:]))
        for off in (0, 32):
            checksum = sum(bank[off:off + 1] + bank[off + 2:off + 16])
            while checksum > 255:
                checksum = (checksum & 255) + (checksum >> 8)
            self.assertEqual(bank[off + 1], checksum)
        cpu = nodes[b'cpus']['children'][0]
        self.assertEqual(struct.unpack('<Q', cpu['timebase-frequency'])[0], 13000000)
        io = nodes[b'arm-io']
        uart = next(n for n in io['children'] if n['name'] == b'uart0\0')
        self.assertEqual(struct.unpack('<QQ', uart['reg']), (0x05002000, 0x1000))

    def test_ramdisk_adt(self):
        tree, _ = parse_adt(p.make_adt(bytes(64), [(0x45000000, 0x2000000), (0x49000000, 0x4000000)]))
        chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
        memory = next(n for n in chosen['children'] if n['name'] == b'memory-map\0')
        self.assertEqual(memory['RAMDisk'], struct.pack('<QQ', 0x45000000, 0x2000000))
        self.assertEqual(memory['RAMDisk1'], struct.pack('<QQ', 0x49000000, 0x4000000))

    def test_native_lab_handoff_is_opt_in_and_has_no_unmodeled_claims(self):
        for enabled in (False, True):
            tree, _ = parse_adt(p.make_adt(bytes(64), native_lab_i2c=enabled))
            chosen = next(n for n in tree['children'] if n['name'] == b'chosen\0')
            children = {n['name']: n for n in chosen['children']}
            self.assertEqual(b'mt6762-handoff\0' in children, enabled)
            if enabled:
                handoff = children[b'mt6762-handoff\0']
                self.assertEqual(handoff['version'], struct.pack('<I', 1))
                self.assertEqual(handoff['lab-fixture'], struct.pack('<I', 1))
                self.assertEqual(handoff['i2c-parent-hz'], struct.pack('<I', 26000000))
                self.assertEqual(handoff['touch-address'], struct.pack('<I', 0x3b))
                for unmodeled in ('display-verified', 'pwrap-verified', 'adc-verified', 'keypad-verified'):
                    self.assertNotIn(unmodeled, handoff)

    def test_synthetic_framebuffer(self):
        args = BootArgs.from_buffer_copy(p.boot_args(0x44000000, 32, 0x45000000, '', 0x44800000))
        self.assertEqual((args.video.base, args.video.width, args.video.height, args.video.rowBytes, args.video.depth),
                         (0x44800000, 384, 854, 1536, 32))
        tree, _ = parse_adt(p.make_adt(bytes(64), framebuffer=True))
        io = next(n for n in tree['children'] if n['name'] == b'arm-io\0')
        self.assertNotIn(b'disp0\0', [n['name'] for n in io['children']])

    def test_generated_identity_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'identity.h'
            data = ','.join(str(x) for x in b'iPhone10,3\0')
            path.write_text('static const struct identity_prop identity_root[] = {{"model",0,11}};\n'
                            'static const unsigned char identity_root_data[] = {' + data + '};\n'
                            'static const struct identity_prop identity_product[] = {{"foo",0,1}};\n'
                            'static const unsigned char identity_product_data[] = {1};\n')
            identity = p.load_identity(path)
            self.assertEqual(identity['root'], [('model', b'iPhone10,3\0')])
            path.write_text(path.read_text().replace('"foo",0,1', '"foo",1,1'))
            with self.assertRaises(ValueError):
                p.load_identity(path)


if __name__ == '__main__':
    unittest.main()
