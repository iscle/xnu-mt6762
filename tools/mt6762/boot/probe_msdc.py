#!/usr/bin/env python3
"""Bounded native MSDC test against an explicit real read-only raw file fixture."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time

FAULTS = ('none','busy','queue','crypto','stale-irq','command-crc','command-timeout',
          'data-crc','short-data','missing-done','ack-stuck','backend-error','wrong-r1',
          'extcsd-partition','extcsd-queue','extcsd-bus','extcsd-timing','extcsd-capacity')


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def fnv1a(data):
    value=2166136261
    for byte in data:value=((value^byte)*16777619)&0xffffffff
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--seconds',type=float,default=15)
    parser.add_argument('--ios-slice',action='store_true',help='test /dev/mtkios0 with an ios-configured PID1 probe')
    parser.add_argument('--fault',choices=FAULTS,default='none')
    parser.add_argument('--expect-admission-rejected',action='store_true',
                        help='Explicit malformed native handoff must expose no readable device')
    parser.add_argument('--expect-no-commands',action='store_true',
                        help='With rejected admission, require zero model commands')
    parser.add_argument('--fault-after-first-read',action='store_true')
    parser.add_argument('--clear-after-error',action='store_true')
    parser.add_argument('--label',default='msdc')
    args=parser.parse_args()
    if not 1<=args.seconds<=60 or not re.fullmatch(r'[A-Za-z0-9_-]+',args.label):
        parser.error('Choose1..60 seconds and a simple new label')
    if args.expect_admission_rejected and args.fault_after_first_read:parser.error('Rejected admission cannot use delayed faults')
    if args.expect_no_commands and not args.expect_admission_rejected:parser.error('Zero-command assertion requires rejected admission')
    if args.fault_after_first_read and args.fault=='none':parser.error('Select a fault to inject')
    if args.fault_after_first_read and args.fault=='extcsd-bus':
        parser.error('Write-only BUS_WIDTH readback variation is a startup regression, not a transfer fault')
    if args.clear_after_error and not args.fault_after_first_read:parser.error('Clearing requires delayed fault injection')
    manifest=json.loads(args.manifest.read_text())
    metadata=manifest.get('native_lab_msdc_image')
    if not manifest.get('native_lab_msdc') or not metadata or not metadata['readonly']:
        parser.error('Manifest must explicitly enable a read-only MSDC image')
    source=Path(metadata['file'])
    before=digest(source)
    if before!=metadata['sha256']:parser.error('Backing file changed since preparation')
    sectors=metadata['sector_count']
    start=0
    if args.ios_slice:
        extent=manifest.get('native_lab_ios_slice')
        if not extent or len(extent)!=2:parser.error('Manifest has no explicit iOS slice')
        start,sectors=extent
        if start<0 or sectors<=0 or start+sectors>metadata['sector_count']:parser.error('Invalid slice extent')
    expected={}
    with source.open('rb') as backing:
        for lba in {0,min(1,sectors-1),sectors-1}:
            backing.seek((start+lba)*512);expected[lba]=fnv1a(backing.read(512))
    command=list(manifest['command'])
    if args.fault!='none' and not args.fault_after_first_read:
        command[command.index('-M')+1]+=',lab-msdc-fault='+args.fault
    out=args.manifest.resolve().parent
    log=out/(args.label+'.serial.log');sock=out/(args.label+'.qmp')
    result_path=out/(args.label+'.json')
    if any(p.exists() for p in (log,sock,result_path)):parser.error('Evidence label already exists')
    proc=client=reader=None;states=[];injected=cleared=False;run_error=None
    qemu_hash=digest(Path(command[0]))
    try:
        with log.open('x') as serial:
            proc=subprocess.Popen(command+['-qmp',f'unix:{sock},server=on,wait=off'],stdout=serial,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+15
            while not sock.exists():
                if proc.poll() is not None:raise RuntimeError('QEMU exited before QMP')
                if time.monotonic()>deadline:raise RuntimeError('QMP startup timed out')
                time.sleep(.02)
            client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);client.settimeout(5);client.connect(str(sock))
            reader=client.makefile('rb');greeting=json.loads(reader.readline())
            if 'QMP' not in greeting:raise RuntimeError('Missing QMP greeting')
            def execute(name,**arguments):
                client.sendall((json.dumps({'execute':name,'arguments':arguments})+'\n').encode())
                while True:
                    line=reader.readline()
                    if not line:raise RuntimeError('QMP closed')
                    reply=json.loads(line)
                    if 'error' in reply:raise RuntimeError(reply['error'])
                    if 'return' in reply:return reply['return']
            execute('qmp_capabilities');started=time.monotonic()
            while time.monotonic()-started<args.seconds:
                if proc.poll() is not None:raise RuntimeError('QEMU exited during native probe')
                observed=log.read_text(errors='replace')
                state=json.loads(execute('qom-get',path='/machine',property='lab-msdc-state'))
                states.append({'elapsed_seconds':round(time.monotonic()-started,3),'state':state})
                if args.fault_after_first_read and not injected and re.search(r'MT6762_MSDC_READ kind=char lba=0 result=512 ',observed):
                    execute('qom-set',path='/machine',property='lab-msdc-fault',value=args.fault);injected=True
                if args.clear_after_error and injected and not cleared and re.search(r'MT6762_MSDC_READ .*result=-\d+',observed):
                    execute('qom-set',path='/machine',property='lab-msdc-fault',value='none');cleared=True
                if 'MT6762_MSDC_PROBE_DONE' in observed or 'panic(' in observed:break
                time.sleep(.01)
            execute('stop')
            states.append({'elapsed_seconds':round(time.monotonic()-started,3),
                           'state':json.loads(execute('qom-get',path='/machine',property='lab-msdc-state'))})
            execute('quit')
    except Exception as error:
        run_error=str(error)
    finally:
        if reader:reader.close()
        if client:client.close()
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    text=log.read_text(errors='replace') if log.exists() else ''
    after=digest(source)
    scalars={name:int(value) for name,value in re.findall(r'MT6762_MSDC (\w+)=(-?\d+)',text)}
    diagnostics={name:{'value':int(value),'error':int(error)} for name,value,error in
                 re.findall(r'MT6762_MSDC_SYSCTL (\w+)=(-?\d+) error=(-?\d+)',text)}
    reads=[dict(kind=kind,lba=int(lba),result=int(result),fnv1a=int(value)) for kind,lba,result,value in
           re.findall(r'MT6762_MSDC_READ kind=(\w+) lba=(\d+) result=(-?\d+) fnv1a=(\d+)',text)]
    ranges=[dict(offset=int(offset),count=int(count),result=int(result),fnv1a=int(value)) for offset,count,result,value in
            re.findall(r'MT6762_MSDC_RANGE offset=(\d+) count=(\d+) result=(-?\d+) fnv1a=(\d+)',text)]
    cpus=sorted(set(int(n) for n in re.findall(r'arm_cpu_init\(\): cpu (\d+) online',text)))
    errors=[]
    if run_error:errors.append(run_error)
    if scalars.get('ios_slice',0)!=int(args.ios_slice):errors.append('Probe device selection does not match requested slice')
    if 'panic(' in text:errors.append('Kernel panic observed')
    if before!=after:errors.append('Backing image changed')
    if 'MT6762_MSDC_PROBE_DONE' not in text:errors.append('Guest probe did not finish')
    if cpus!=list(range(1,manifest.get('cpu_count',1))):errors.append('Secondary CPU online proof incomplete')
    if not states or not states[-1]['state'].get('readonly'):errors.append('Model did not confirm read-only backend')
    if any(v['error'] for v in diagnostics.values()) or len(diagnostics)!=5:errors.append('Native storage diagnostics unavailable')
    if (args.fault in ('none','extcsd-bus','backend-error') or args.fault_after_first_read) and not args.expect_admission_rejected:
        if not (scalars.get('char_open',-1)>=0 and scalars.get('write_open')==-30 and
                scalars.get('blocksize')==512 and scalars.get('blockcount')==sectors and
                scalars.get('writable')==0 and all(scalars.get(k)==0 for k in ('blocksize_error','blockcount_error','writable_error'))):
            errors.append('Device geometry/read-only admission proof failed')
    # Legacy model knob changes an undefined BUS_WIDTH readback byte. Both
    # zero and nonzero values must allow otherwise valid read-only access.
    if args.fault in ('none','extcsd-bus') and not args.expect_admission_rejected:
        wanted=[('char',0),('char',1),('char',sectors-1),('block',0)] if sectors>1 else [('char',0),('char',0),('block',0)]
        if [(r['kind'],r['lba']) for r in reads]!=wanted:errors.append('Expected raw and block reads missing')
        if any(r['result']!=512 or r['fnv1a']!=expected[r['lba']] for r in reads):errors.append('Guest bytes differ from real backing-file sectors')
        if states and states[-1]['state']['backend_reads']<len(reads):errors.append('Reads lack real backend activity')
        expected_ranges=[(480,64)] if sectors>1 else []
        if args.ios_slice and sectors>=256:expected_ranges.append((0,128*1024))
        expected_ranges += [(sectors*512-16,32),(sectors*512,512),((sectors+1)*512,512)]
        # XNU permits negative lseek onVCHR; the driver must reject the read.
        if scalars.get('negative_seek')!=-1 or scalars.get('negative_read')!=-22 or scalars.get('negative_buffer')!=0xa5:
            errors.append('Negative character offset read was not rejected withoutcopying')
        if [(r['offset'],r['count']) for r in ranges]!=expected_ranges:errors.append('Unaligned/EOF range observations missing')
        with source.open('rb') as backing:
            for r in ranges:
                backing.seek(start*512+r['offset']);data=backing.read(max(0,min(r['count'],sectors*512-r['offset'])))
                payload=data+bytes([0xa5])*(r['count']-len(data))
                if r['result']!=len(data) or r['fnv1a']!=fnv1a(payload):errors.append('Range/EOF result differs from real file bytes')

    elif args.fault=='backend-error' and not args.fault_after_first_read and not args.expect_admission_rejected:
        # CMD8 metadata needs no backend payload. Admission can complete before
        # the first CMD17 backend failure; no fabricated userdata is acceptable.
        sentinel=fnv1a(bytes([0xa5])*512)
        if len(reads)<3 or any(r['result']>=0 or r['fnv1a']!=sentinel for r in reads):
            errors.append('Startup backend failure returned or copied payload')
        if (diagnostics.get('mt6762_msdc_ready',{}).get('value')!=0 or
            diagnostics.get('mt6762_msdc_fault',{}).get('value')!=1):
            errors.append('Backend failure did not invalidate and latch native transport')
        if states and (states[-1]['state']['backend_errors']!=1 or states[-1]['state']['backend_reads']!=1):
            errors.append('Expected exactly one failed backend attempt before native latch')
    elif args.fault_after_first_read:
        if not injected:errors.append('Delayed fixture fault was not injected')
        if args.clear_after_error and not cleared:errors.append('Fixture fault was not cleared after native error')
        if not reads or reads[0]['result']!=512 or reads[0]['fnv1a']!=expected[0]:errors.append('No valid read before fault')
        sentinel=fnv1a(bytes([0xa5])*512)
        if len(reads)<3 or any(r['result']>=0 or r['fnv1a']!=sentinel for r in reads[1:]):errors.append('Faulted transport returned or copied payload')
        if diagnostics.get('mt6762_msdc_fault',{}).get('value')!=1:errors.append('Native transport did not latch fault')
    else:
        if scalars.get('char_open',0)>=0 or reads:errors.append('Faulted inherited state exposed readable device')
        if diagnostics.get('mt6762_msdc_ready',{}).get('value')!=0:errors.append('Faulted transport reports ready')
        if args.expect_no_commands and states and states[-1]['state']['commands']:
            errors.append('Rejected native ownership still issued storage commands')
    result=dict(synthetic_only=True,physical_hardware_tested=False,passed=not errors,errors=errors,
                kernel_sha256=manifest['kernel_sha256'],qemu_binary_sha256=qemu_hash,
                image_sha256_before=before,image_sha256_after=after,sector_count=sectors,
                slice_start_sector=start,ios_slice=args.ios_slice,
                expected_admission_rejected=args.expect_admission_rejected,
                expected_no_commands=args.expect_no_commands,
                startup_fault=args.fault if not args.fault_after_first_read else 'none',
                delayed_fault=args.fault if args.fault_after_first_read else 'none',
                fault_injected=injected,fault_cleared_after_error=cleared,
                secondary_cpus_online=cpus,guest_scalars=scalars,native_sysctls=diagnostics,
                guest_reads=reads,guest_ranges=ranges,model_samples=states,
                serial_sha256=digest(log) if log.exists() else None)
    result_path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':not errors,'errors':errors,'result':str(result_path)}))
    raise SystemExit(bool(errors))


if __name__=='__main__':main()
