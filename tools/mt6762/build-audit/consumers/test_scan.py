import struct
import unittest
from scan_consumers import parse_macho, bind_symbols


def header(commands, tail=b''):
    return struct.pack('<8I',0xfeedfacf,0x100000c,0,11,1,len(commands),0,0)+commands+tail


class ImportTests(unittest.TestCase):
    def test_undefined_not_definition_or_debug(self):
        strings=b'\0_target\0_target_extra\0'
        entries=b''.join(struct.pack('<IBBHQ',idx,kind,0,0,0)
                         for idx,kind in [(1,1),(9,1),(1,0xf),(1,0xe1)])
        cmd=struct.pack('<6I',2,24,56,4,56+len(entries),len(strings))
        _,imports=parse_macho(header(cmd,entries+strings))
        self.assertEqual(set(imports),{'_target','_target_extra'})
        self.assertEqual(set(imports)&{'_target'},{'_target'})

    def test_malformed_symbol_table(self):
        with self.assertRaises(ValueError):
            parse_macho(header(struct.pack('<6I',2,24,56,0xffffffff,56,1),b'\0'))

    def test_chained_format_1_2_3(self):
        for fmt,stride in [(1,4),(2,8),(3,16)]:
            # Name offset1; signed special library ordinal preserved as irrelevant
            # to exact symbol identity. Addend bytes must not become name offsets.
            entry=(struct.pack('<Qq',(1<<32)|0xffff,-123) if fmt==3 else
                   struct.pack('<I',(1<<9)|0xff)+(struct.pack('<i',-123) if fmt==2 else b''))
            blob=struct.pack('<7I',0,28,28,28+stride,1,fmt,0)+entry+b'\0_target\0'
            meta,imports=parse_macho(header(struct.pack('<4I',0x80000034,16,48,len(blob)),blob))
            self.assertEqual(set(imports),{'_target'})
            self.assertEqual(meta['import_tables'][0]['import_count'],1)

    def test_bind_requires_real_operation(self):
        self.assertEqual(bind_symbols(b'\x40_target\0\x90\0'),{'_target'})
        self.assertEqual(bind_symbols(b'\x40_target\0\0'),set())
        with self.assertRaises(ValueError):bind_symbols(b'\x90')
        with self.assertRaises(ValueError):bind_symbols(b'\xd0')

    def test_unterminated_or_out_of_bounds_chained_name(self):
        blob=struct.pack('<7I',0,28,28,32,1,1,0)+struct.pack('<I',0)+b'x'
        with self.assertRaises(ValueError):
            parse_macho(header(struct.pack('<4I',0x80000034,16,48,len(blob)),blob))


if __name__=='__main__':unittest.main()
