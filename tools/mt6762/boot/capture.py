#!/usr/bin/env python3
"""Run an existing lab manifest and capture its synthetic framebuffer via QMP.

The PNG is a RAM snapshot, not proof of a real MediaTek display driver.
This launches no hardware connection and always terminates its own QEMU.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import socket
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--seconds', type=float, default=75)
    parser.add_argument('--label', default='capture')
    parser.add_argument('--native-input-schedule', type=Path,
                        help='JSON timed synthetic PMIC key/AXS gestures, never guest queue injection')
    parser.add_argument('--stop-on-panic', action='store_true')
    parser.add_argument('--stop-on-storage-error', action='store_true')
    parser.add_argument('--host-scheduling', action='store_true',
                        help='Record bounded Linux host vCPU scheduling counters for timeout diagnosis')
    parser.add_argument('--gauge-clock-fault-at', type=float,
                        help='Inject synthetic gauge clock loss at this elapsed second; explicit gauge fixture required')
    parser.add_argument('--sample-every', type=float, default=0,
                        help='Also save numbered framebuffer snapshots at this interval')
    args = parser.parse_args()
    if args.seconds < 0 or args.sample_every < 0 or '/' in args.label or not args.label:
        raise ValueError('Invalid capture duration or label')
    manifest = json.loads(args.manifest.read_text())
    fb = manifest.get('framebuffer')
    if not fb or not fb.get('simulated_ram_only'):
        raise ValueError('Manifest has no synthetic framebuffer')
    if args.gauge_clock_fault_at is not None and (not manifest.get('native_lab_gauge') or not 0<=args.gauge_clock_fault_at<args.seconds):
        raise ValueError('Gauge clock fault requires its explicit fixture and a time inside the bounded run')
    gauge_clock_fault_injected=None
    schedule = []
    if args.native_input_schedule:
        from touch_lab import frame, send_frame
        if not manifest.get('native_lab_i2c') or not manifest.get('native_lab_power'):
            raise ValueError('Native schedule requires I2C and power fixture manifests')
        schedule = json.loads(args.native_input_schedule.read_text())
        if not isinstance(schedule,list) or len(schedule)>100:
            raise ValueError('Native schedule must contain at most100 actions')
        for action in schedule:
            if not isinstance(action,dict) or not 0<=action.get('at',-1)<args.seconds:
                raise ValueError('Schedule time is outside the bounded run')
            if 'keys' in action:
                if set(action)-{'at','keys','hold'} or not isinstance(action['keys'],int) or not 0<=action['keys']<=7 or not .05<=action.get('hold',.15)<=2:
                    raise ValueError('Invalid synthetic key action')
            elif 'from' in action:
                if set(action)-{'at','from','to','steps'} or not 2<=action.get('steps',24)<=120:
                    raise ValueError('Invalid synthetic touch action')
                frame([(0,*action['from'])]);frame([(0,*action.get('to',action['from']))])
            else:
                raise ValueError('Unknown schedule action')
        if [a['at'] for a in schedule]!=sorted(a['at'] for a in schedule):
            raise ValueError('Schedule actions must be ordered')
    actions=[];next_action=0;panic_observed=False;storage_failure_observed=False
    out = args.manifest.resolve().parent
    sockpath = out / (args.label + '.qmp')
    # Never unlink an existing monitor: another experiment may own it.
    if sockpath.exists():
        raise ValueError('QMP socket already exists: ' + str(sockpath))
    raw = out / (args.label + '.bgra')
    transcript = []
    model_states = []
    qemu_sha256 = hashlib.sha256(Path(manifest['command'][0]).read_bytes()).hexdigest()
    qemu = None
    host_scheduling = None
    run_completed = False
    with (out / (args.label + '.serial.log')).open('w') as serial:
        try:
            qemu = subprocess.Popen(manifest['command'] + ['-qmp', f'unix:{sockpath},server=on,wait=off'],
                                    stdout=serial, stderr=subprocess.STDOUT)
            for _ in range(100):
                if qemu.poll() is not None:
                    raise RuntimeError('QEMU exited before QMP became available')
                if sockpath.exists():
                    break
                time.sleep(0.1)
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(10)
                client.connect(str(sockpath))
                reader = client.makefile('rb')
                transcript.append(json.loads(reader.readline()))

                def execute(command, arguments=None):
                    request = {'execute': command}
                    if arguments is not None:
                        request['arguments'] = arguments
                    client.sendall(json.dumps(request).encode() + b'\n')
                    while True:
                        result = json.loads(reader.readline())
                        transcript.append(result)
                        if 'error' in result:
                            raise RuntimeError(result['error'])
                        if 'return' in result:
                            return result['return']

                execute('qmp_capabilities')
                if args.host_scheduling:
                    from host_scheduling import HostScheduling
                    host_scheduling = HostScheduling(qemu.pid, execute('query-cpus-fast'))
                def record_models():
                    states = {}
                    for option, prop in [('native_lab_i2c', 'lab-i2c-state'),
                                         ('native_lab_display', 'lab-display-state'),
                                         ('native_lab_power', 'lab-power-state'),
                                         ('native_lab_msdc_image', 'lab-msdc-state'),
                                         ('native_lab_sspm', 'lab-sspm-state')]:
                        if manifest.get(option):
                            states[prop] = json.loads(execute('qom-get', {'path':'/machine', 'property':prop}))
                    if states:
                        model_states.append({'elapsed_seconds':round(time.monotonic()-started,3), 'states':states})
                started = time.monotonic()
                deadline = started + args.seconds
                next_sample = started + args.sample_every if args.sample_every else deadline
                sample = 0
                while time.monotonic() < deadline:
                    if host_scheduling:
                        host_scheduling.sample()
                    if qemu.poll() is not None:
                        raise RuntimeError('QEMU exited during capture wait')
                    if args.stop_on_panic and 'panic(' in (out / (args.label + '.serial.log')).read_text(errors='replace'):
                        panic_observed=True
                        break
                    if args.stop_on_storage_error and 'MSDC: terminal read failure' in (out / (args.label + '.serial.log')).read_text(errors='replace'):
                        storage_failure_observed=True
                        break
                    if args.gauge_clock_fault_at is not None and gauge_clock_fault_injected is None and time.monotonic()-started>=args.gauge_clock_fault_at:
                        execute('qom-set',{'path':'/machine','property':'lab-power-fault','value':'gauge-clock'})
                        gauge_clock_fault_injected=round(time.monotonic()-started,3)
                        record_models()
                    if next_action<len(schedule) and time.monotonic()-started>=schedule[next_action]['at']:
                        action=schedule[next_action]
                        if 'keys' in action:
                            execute('qom-set',{'path':'/machine','property':'lab-key-mask','value':action['keys']})
                            time.sleep(action.get('hold',.15))
                            execute('qom-set',{'path':'/machine','property':'lab-key-mask','value':0})
                        else:
                            begin=action['from'];end=action.get('to',begin);steps=action.get('steps',24)
                            def command(name,**arguments): return execute(name,arguments)
                            for i in range(steps):
                                point=[round(begin[n]+(end[n]-begin[n])*i/(steps-1)) for n in (0,1)]
                                send_frame(command,[(0,*point)])
                            send_frame(command,[])
                        actions.append({'elapsed_seconds':round(time.monotonic()-started,3),'action':action,'completed':True})
                        next_action+=1
                        record_models()
                    if args.sample_every and time.monotonic() >= next_sample:
                        sample += 1
                        sample_raw = out / f'{args.label}-{sample:03d}.bgra'
                        execute('stop')
                        record_models()
                        execute('pmemsave', {'val': fb['addr'], 'size': fb['size'], 'filename': str(sample_raw)})
                        execute('cont')
                        save_png(sample_raw, fb)
                        next_sample += args.sample_every
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
                execute('stop')
                if host_scheduling:
                    host_scheduling.sample()
                panic_observed |= 'panic(' in (out / (args.label + '.serial.log')).read_text(errors='replace')
                if panic_observed:
                    registers=[]
                    for cpu in range(manifest.get('cpu_count',1)):
                        execute('human-monitor-command',{'command-line':f'cpu {cpu}'})
                        regs=execute('human-monitor-command',{'command-line':'info registers'})
                        entry={'cpu':cpu,'registers':regs,'frame_chain':[]}
                        found=re.search(r'X29\s*=\s*([0-9a-fA-F]+)',regs)
                        fp=int(found.group(1),16) if found else 0
                        seen=set()
                        for _ in range(8):
                            if fp in seen or fp & 15 or fp<0xffff000000000000: break
                            seen.add(fp)
                            memory=execute('human-monitor-command',{'command-line':f'x /2gx {fp:#x}'})
                            entry['frame_chain'].append({'fp':hex(fp),'memory':memory})
                            found=re.search(r':\s*(?:0x)?([0-9a-fA-F]{16})',memory)
                            if not found: break
                            fp=int(found.group(1),16)
                        registers.append(entry)
                    (out / (args.label + '.panic-registers.json')).write_text(json.dumps(registers,indent=2)+'\n')
                record_models()
                execute('pmemsave', {'val': fb['addr'], 'size': fb['size'], 'filename': str(raw)})
                execute('quit')
                run_completed = True
                reader.close()
        finally:
            if qemu is not None and qemu.poll() is None:
                qemu.terminate()
                try:
                    qemu.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    qemu.kill()
                    qemu.wait()
            if host_scheduling:
                (out / (args.label + '.host-scheduling.json')).write_text(
                    json.dumps(host_scheduling.report, indent=2) + '\n')
            (out / (args.label + '.qmp.json')).write_text(json.dumps(transcript, indent=2) + '\n')
            (out / (args.label + '.models.json')).write_text(json.dumps({
                'synthetic_only':True, 'run_completed':run_completed, 'kernel_sha256':manifest['kernel_sha256'],
                'qemu_binary_sha256':qemu_sha256, 'samples':model_states,
                'native_input_actions':actions,'kernel_panic_observed':panic_observed,
                'terminal_storage_failure_observed':storage_failure_observed,
                'gauge_clock_fault_injected_seconds':gauge_clock_fault_injected,
                'native_input_schedule_sha256':hashlib.sha256(args.native_input_schedule.read_bytes()).hexdigest() if args.native_input_schedule else None}, indent=2) + '\n')
    filename, visible = save_png(raw, fb)
    print(json.dumps({'png': str(filename), 'distinct_bytes': len(set(visible)),
                      'synthetic_ram_only': True,'native_input_actions_completed':len(actions),
                      'kernel_panic_observed':panic_observed}))
    if panic_observed: raise SystemExit(1)


def save_png(raw, fb):
    from PIL import Image
    data = raw.read_bytes()
    visible = data[:fb['stride'] * fb['height']]
    image = Image.frombytes('RGBA', (fb['width'], fb['height']), visible, 'raw', 'BGRA', fb['stride'])
    filename = raw.with_suffix('.png')
    image.convert('RGB').save(filename)
    return filename, visible


if __name__ == '__main__':
    main()
