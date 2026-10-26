"""Physical PSC read grants remain zero until the loader accepts live entry."""
from pathlib import Path
import struct,subprocess,sys,unittest
import build_payload as build

class ChargerReadonlyProducerTests(unittest.TestCase):
    def test_closed_readonly_properties(self):
        p=build.charger_readonly_properties()
        self.assertEqual(set(p),set(build.CHARGER_READONLY_FLAGS)|{'i2c-parent-index','i2c-parent-hz','i2c5-hz'})
        for name in build.CHARGER_READONLY_FLAGS:self.assertEqual(p[name],bytes(4))
        for name,value in {'i2c-parent-index':2,'i2c-parent-hz':124800000,'i2c5-hz':100000}.items():
            self.assertEqual(p[name],struct.pack('<I',value))
        self.assertNotIn('charger-setup-only',p)
        self.assertNotIn('charger-control-owned',p)
        self.assertNotIn('pwrap-write-owned',p)
        t={'name':'device-tree','props':{},'children':[{'name':'chosen','props':{},'children':[
            {'name':'mt6762-handoff','props':p,'children':[]}]}]}
        raw=build.encode_adt(t);tree,end,positions=build.decode_adt(raw)
        self.assertEqual(end,len(raw));self.assertEqual(tree['children'][0]['children'][0]['props'],p)
        for name in build.CHARGER_READONLY_FLAGS:
            o=positions['/device-tree/chosen/mt6762-handoff/'+name]
            self.assertEqual(raw[o:o+4],bytes(4))

    def test_requires_both_consumer_implementations(self):
        markers=(b'MT6762_PSC_READONLY_ADMITTED transactions=6\n\0',b'MT6762_PSC_PROBE pass=')
        build.require_charger_readonly_kernel(b'',False)
        for data in (b'',*markers):
            with self.assertRaises(ValueError):build.require_charger_readonly_kernel(data,True)
        build.require_charger_readonly_kernel(b'\0'.join(markers),True)

    def test_cli_dependencies_and_mutual_exclusion_precede_io(self):
        base=[sys.executable,str(Path(build.__file__)),'--kernel','/absent/kernel','--template','/absent/template',
              '--llvm','/absent/llvm','--out','/absent/output','--diagnostic','/absent/pid1',
              '--native-charger-readonly-probe']
        for extra,reason in (([],b'charger reads require'),(['--native-pwrap-probe'],b'requires native display and passive'),
            (['--native-charger-setup-probe'],b'not allowed with argument')):
            r=subprocess.run(base+extra,capture_output=True,timeout=10)
            self.assertEqual(r.returncode,2);self.assertIn(reason,r.stderr);self.assertNotIn(b'FileNotFoundError',r.stderr)

if __name__=='__main__':unittest.main()
