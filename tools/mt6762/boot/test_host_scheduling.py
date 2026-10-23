import tempfile
import unittest
from pathlib import Path
from host_scheduling import HostScheduling


class HostSchedulingTests(unittest.TestCase):
    def test_partial_accounting_does_not_fabricate_idle_cpu(self):
        with tempfile.TemporaryDirectory() as name:
            proc = Path(name)
            task = proc / '10/task/11'
            task.mkdir(parents=True)
            (task / 'schedstat').write_text('1000000000 200000000 7\n')
            observer = HostScheduling(10, [{'cpu-index': 0, 'thread-id': 11},
                                           {'cpu-index': 1, 'thread-id': 12}], proc)
            observer.sample()
            threads = observer.report['samples'][0]['threads']
            self.assertEqual(threads[0]['runtime_ns'], 1000000000)
            self.assertEqual(threads[0]['runqueue_wait_ns'], 200000000)
            self.assertEqual(threads[1]['error'], 'FileNotFoundError')
            self.assertNotIn('runtime_ns', threads[1])
            (task / 'schedstat').write_text('1 -1 3\n')
            observer.sample()
            self.assertEqual(observer.report['samples'][1]['threads'][0]['error'], 'ValueError')
            self.assertNotIn('runtime_ns', observer.report['samples'][1]['threads'][0])

    def test_observation_bound(self):
        observer = HostScheduling(1, [])
        for _ in range(2050):
            observer.sample()
        self.assertEqual(len(observer.report['samples']), 2048)
        self.assertTrue(observer.report['truncated'])


if __name__ == '__main__':
    unittest.main()
