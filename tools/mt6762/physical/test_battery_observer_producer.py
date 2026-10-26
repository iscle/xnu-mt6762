from pathlib import Path
import subprocess,sys,unittest
import build_payload as build

class BatteryObserverProducerTests(unittest.TestCase):
    def test_unpatched_handoff_never_grants_observation(self):
        for gauge in (False,True):
            p=build.battery_observer_properties(gauge)
            flags=set(build.BATTERY_OBSERVER_FLAGS)
            if gauge:flags|={'fgauge-inherited-observer',*build.GAUGE_OBSERVER_VALUES}
            for k in flags:self.assertEqual(p[k],bytes(4))
            for k in ('charger-setup-only','charger-readonly-probe','charger-control-owned',
                      'pwrap-write-owned','fgauge-owned','fgauge-calibration-verified','adc-verified'):
                self.assertNotIn(k,p)
            raw=build.encode_adt({'name':'device-tree','props':p,'children':[]})
            decoded,end,positions=build.decode_adt(raw)
            self.assertEqual(end,len(raw));self.assertEqual(decoded['props'],p)
            for k in flags:self.assertEqual(raw[positions['/device-tree/'+k]:][:4],bytes(4))

    def test_old_kernel_cannot_receive_new_observer(self):
        markers=(b'MT6762_PSC_OBSERVER_ADMITTED reads=3,1,0 min_period_us=500000\n\0',
                 b'MT6762_BATTERY_OBSERVER_READY',b'MT6762_GAUGE_OBSERVER_READY')
        for missing in range(3):
            with self.assertRaises(ValueError):
                build.require_battery_observer_kernel(b''.join(m for i,m in enumerate(markers) if i!=missing),True,True)
        build.require_battery_observer_kernel(b''.join(markers),True,True)

    def test_incompatible_requests_fail_before_artifact_access(self):
        base=[sys.executable,str(Path(build.__file__)),'--kernel','/absent/kernel',
              '--template','/absent/template','--llvm','/absent/llvm','--out','/absent/out',
              '--diagnostic','/absent/pid1']
        for args,reason in ((['--native-battery-observer'],b'battery observer requires'),
                           (['--native-gauge-observer'],b'gauge observer requires'),
                           (['--native-battery-observer','--native-charger-readonly-probe'],b'not allowed with')):
            r=subprocess.run(base+args,capture_output=True,timeout=10)
            self.assertEqual(r.returncode,2);self.assertIn(reason,r.stderr)
            self.assertNotIn(b'FileNotFoundError',r.stderr)

if __name__=='__main__':unittest.main()
