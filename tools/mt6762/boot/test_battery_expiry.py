"""Log acceptance boundaries; fixture tests do not constitute native evidence."""
import unittest
import check_battery_expiry as c


def samples():
    result = []
    for i, expired in enumerate((False, True, True, False)):
        props = {k:'<absent>' for k in c.UNKNOWN+c.MEASURED}
        props.update(MT6762ValidFields='sint32:0' if expired else 'sint32:79',
                     MT6762ReportExpired='bool:1' if expired else 'bool:0')
        if not expired:
            props.update(Voltage='sint32:4400', Amperage='sint32:31', InstantAmperage='sint32:31')
        result.append(dict(iteration=i,status=0,clock_status=0,monotonic_ns=(i+1)*1000000000,
            count=1,native_service_found=True,snapshot_status=0,properties=props,
            sysctls={'mt6762_power_valid':dict(value=0 if expired else 79,error=0),
                     'mt6762_adc_voltage_requests':dict(value=i+10,error=0)}))
    return result


class BatteryExpiryTests(unittest.TestCase):
    def test_requires_valid_expired_recovered_and_continued_acquisition(self):
        values=samples()
        self.assertEqual(c.check(values,True)[0],[])
        values[2]['sysctls']['mt6762_adc_voltage_requests']['value']=11
        self.assertTrue(c.check(values,True)[0])

    def test_rejects_fabricated_unknown_or_retained_current(self):
        values=samples();values[0]['properties']['Temperature']='sint32:2500'
        self.assertTrue(c.check(values)[0])
        values=samples()
        for i in (1,2):values[i]['properties']['Amperage']='sint32:31'
        self.assertTrue(c.check(values)[0])

    def test_rejects_missing_recovery(self):
        self.assertTrue(c.check(samples()[:-1])[0])

    def test_native_properties_are_not_overwritten_by_legacy_service(self):
        log='MT6762_BAT_PROBE iteration=1 readonly=1 status=0 monotonic_ns=100 clock_status=0\n'
        log+='MT6762_BAT_SERVICE name=MT6762Battery class=RedwoodBattery\n'
        log+='MT6762_BAT_SNAPSHOT status=0\nMT6762_BAT_PROPERTY Voltage=<absent>\n'
        log+='MT6762_BAT_SERVICE name=RedwoodBattery class=RedwoodBattery\n'
        log+='MT6762_BAT_SNAPSHOT status=0\nMT6762_BAT_PROPERTY Voltage=sint32:4000\n'
        log+='MT6762_BAT_COUNT 2\n'
        parsed=c.parse(log)
        self.assertEqual(parsed[0]['properties']['Voltage'],'<absent>')


if __name__=='__main__':unittest.main()
