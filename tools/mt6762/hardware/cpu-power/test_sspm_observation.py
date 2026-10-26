import copy
import json
from pathlib import Path
import unittest
from decode_sspm_observation import GROUPS, GUARDS, decode


def fixture():
    sample = {name: [0]*count for name, (count, _) in GROUPS.items()}
    sample['guards'] = GUARDS[:]
    rows = json.loads((Path(__file__).parent / 'evidence/stock-c62-pvt.json').read_text())['rows']
    for domain in range(3):
        for i, (mhz, selector, post, clk) in enumerate(rows[domain*16:(domain+1)*16]):
            sample['pvt'][domain*36+i] = mhz | (selector << 16)
            sample['pvt'][domain*36+16+i] = post | (clk << 16)
        sample['pvt'][domain*36+32] = 0xffffffff
    sample['mailbox'][:2] = [0x80000003, 0x40000003]
    sample['irq'] = [1 << 13, 1 << 13]
    return sample


def record(samples, stable=511, guards=1, c62=1):
    lines = [f'MT6762_SSPM_OBSERVE version=1 passes=2 words=174 stable_groups={stable:03x} '
             f'guards={guards} c62_representation={c62} ownership=0 liveness=unknown']
    for p, sample in enumerate(samples):
        for name, words in sample.items():
            for i in range(0, len(words), 4):
                chunk = words[i:i+4]
                fields = ' '.join(f'{v:08x}' for v in chunk+[0]*(4-len(chunk)))
                lines.append(f'MT6762_SSPM_RAW pass={p} group={name} word={i} count={len(chunk)} {fields}')
    lines.append('MT6762_SSPM_OBSERVE end=1 writes=0')
    return ('\n'.join(lines)+'\n').encode()


class TestObservation(unittest.TestCase):
    def test_c62_is_not_ready(self):
        sample = fixture()
        sample['eem'][0] = 1
        sample['index'][0] = 0xffffffff
        result = decode(record([sample]))
        self.assertTrue(result['c62_representation_match'])
        self.assertFalse(result['controller_ready'])
        self.assertFalse(result['ownership_granted'])
        self.assertFalse(result['interpretation'][0]['eem_flags_clear'])
        self.assertFalse(result['interpretation'][0]['current_indices_in_range'])
        self.assertEqual(result['interpretation'][0]['pending_platform_cpu_out'], 3)
        self.assertTrue(result['interpretation'][0]['mailbox0_irq_active'])

    def test_zero_is_not_initialized(self):
        zero = {name: [0]*count for name, (count, _) in GROUPS.items()}
        self.assertFalse(decode(record([zero], guards=0, c62=0))['c62_representation_match'])

    def test_unstable_retained(self):
        first = fixture()
        second = copy.deepcopy(first)
        second['pvt'][17] ^= 1
        result = decode(record([first, second], stable=511^2, c62=0))
        self.assertFalse(result['matching_second_raw_pass_omitted'])
        self.assertEqual(result['samples'][1]['pvt'][17], second['pvt'][17])

    def test_incomplete_and_duplicates(self):
        lines = record([fixture()]).splitlines(keepends=True)
        for blob in (b''.join(lines[:-1]), b''.join(lines[:2]+lines[3:]),
                     b''.join(lines[:2]+lines[1:]), b''.join(lines+lines)):
            with self.assertRaises(ValueError):
                decode(blob)

    def test_report_disagrees_with_raw(self):
        first = fixture()
        second = copy.deepcopy(first)
        second['index'][0] = 7
        with self.assertRaises(ValueError):
            decode(record([first, second], stable=511^1, guards=0, c62=0))
        first['pvt'][0] ^= 1
        with self.assertRaises(ValueError):
            decode(record([first]))

    def test_bounds_and_padding(self):
        good = record([fixture()])
        for old, new in [(b'word=0 count=4', b'word=999 count=4'),
                         (b'group=eem', b'group=unknown'),
                         (b'word=4 count=1 55aa55aa 00000000', b'word=4 count=1 55aa55aa 00000001'),
                         (b'stable_groups=1ff', b'stable_groups=fff')]:
            with self.assertRaises(ValueError):
                decode(good.replace(old, new, 1))


if __name__ == '__main__':
    unittest.main()
