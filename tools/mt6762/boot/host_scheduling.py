"""Bounded, read-only Linux scheduling observations for a local QEMU process.

Cumulative runqueue time is evidence of host contention, not proof of the cause
of a guest timeout. Sleeping and runnable time must not be conflated. Missing
or disabled kernel accounting remains explicitly unknown.
"""
import time
from pathlib import Path


class HostScheduling:
    def __init__(self, pid, cpus, proc=Path('/proc')):
        self.task = proc / str(pid) / 'task'
        self.cpus = [{'cpu': c['cpu-index'], 'tid': c['thread-id']}
                     for c in cpus]
        if any(type(c['tid']) is not int or c['tid'] <= 0 for c in self.cpus):
            raise ValueError('Invalid QEMU host thread mapping')
        self.report = {
            'source': 'Linux procfs task schedstat', 'pid': pid,
            'units': {'runtime': 'ns', 'runqueue_wait': 'ns', 'timeslices': 'count'},
            'interpretation': 'Cumulative accounting only; zero runqueue time may mean accounting is disabled. No guest-deadlock conclusion.',
            'cpus': self.cpus, 'samples': [], 'truncated': False,
        }
        try:
            self.report['sched_schedstats'] = (proc / 'sys/kernel/sched_schedstats').read_text().strip()
        except OSError as error:
            self.report['sched_schedstats_error'] = type(error).__name__
        self.started = time.monotonic_ns()

    def sample(self):
        if len(self.report['samples']) >= 2048:
            self.report['truncated'] = True
            return
        sample = {'elapsed_ns': time.monotonic_ns() - self.started, 'threads': []}
        for cpu in self.cpus:
            entry = dict(cpu)
            try:
                fields = (self.task / str(cpu['tid']) / 'schedstat').read_text().split()
                if len(fields) != 3 or not all(s.isdecimal() for s in fields):
                    raise ValueError('Invalid schedstat')
                entry.update(zip(('runtime_ns', 'runqueue_wait_ns', 'timeslices'), map(int, fields)))
            except (OSError, ValueError) as error:
                entry['error'] = type(error).__name__
            sample['threads'].append(entry)
        self.report['samples'].append(sample)
