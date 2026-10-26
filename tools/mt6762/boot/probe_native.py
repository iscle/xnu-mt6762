#!/usr/bin/env python3
"""Bounded native-XNU integration probe against opt-in synthetic I2C fixtures."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import socket
import subprocess
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path)
    p.add_argument('--seconds',type=float,default=20)
    p.add_argument('--fault-after-dma-reads',type=int,default=0)
    p.add_argument('--queue-mode',choices=('none','cycle','fault'),default='none',
                   help='Enable synthetic contacts after the static PID1 queue observer is ready')
    p.add_argument('--expect-handoff-rejected',action='store_true',
                   help='Negative test: malformed native handoff must remain headless and perform no transfers')
    p.add_argument('--expect-bif-rejected',action='store_true',
                   help='Negative BIF handoff case: reject admission before any BIF request')
    p.add_argument('--bif-fault',choices=('none','tdet-set','config','trim','timeout','stale','rail','tdet-changed','adc-stale'),default='none')
    p.add_argument('--bif-clear-after-rejection',action='store_true',
                   help='Clear an explicit startup fixture fault after native rejection; require recovery only for generation failures')
    p.add_argument('--bif-fault-after-fresh',action='store_true',
                   help='Inject BIF fault after actual native raw-pair freshness is observed')
    p.add_argument('--expected-gauge-current-ua',type=int,default=31400)
    p.add_argument('--expected-gauge-charge-uah',type=int,default=0)
    p.add_argument('--expect-gauge-charge',action='store_true',
                   help='Require coherent native signed CAR observation (build24 or later)')
    p.add_argument('--gauge-fault',choices=('none','timeout','latch-stuck','stale','clock','calibration','counter-stuck'),default='none')
    p.add_argument('--gauge-fault-after-valid',action='store_true',
                   help='Inject gauge fault after actual native current-valid1 is observed')
    p.add_argument('--thermal-fault-after-fresh',action='store_true',
                   help='Inject requested thermal fault only after actual native fresh-mask7 is observed')
    p.add_argument('--thermal-fault',choices=('none','timeout','stale','uncalibrated','bad-degc','mux','rail'),default='none',
                   help='Startup-only synthetic PMIC conversion/calibration failure')
    p.add_argument('--key-mode',choices=('none','cycle','power-fault','keypad-fault'),default='none',
                   help='Synthetic native power/keypad levels, observed via the kernel input queue')
    p.add_argument('--sspm-fault',choices=('none','timeout','ack-stuck','input-stuck','stale-ack','stale-input','dead','wrong-ack'),default='none',
                   help='Startup synthetic SSPM transport/liveness fault')
    p.add_argument('--display-fault',choices=('none','power-off','scanout-mismatch'),default='none',
                   help='Startup-only synthetic readback failure; expects native display rejection')
    p.add_argument('--label',default='native-probe')
    a=p.parse_args()
    if not 1<=a.seconds<=120 or a.fault_after_dma_reads<0 or not a.label or '/' in a.label:
        raise ValueError('Invalid duration, threshold or label')
    m=json.loads(a.manifest.read_text())
    if not m.get('native_lab_i2c'):
        raise ValueError('Manifest must explicitly select --native-lab-i2c')
    if a.queue_mode!='none' and (m.get('native_lab_touch_events') or a.fault_after_dma_reads):
        raise ValueError('Queue mode needs initially disabled synthetic contacts and no DMA-count fault threshold')
    if a.expect_handoff_rejected and (a.queue_mode!='none' or a.fault_after_dma_reads):
        raise ValueError('Rejected-handoff test cannot also request input/fault injection')
    if a.display_fault!='none' and not m.get('native_lab_display'):
        raise ValueError('Display fault needs --native-lab-display manifest')
    if a.sspm_fault!='none' and not m.get('native_lab_sspm'):
        raise ValueError('SSPM fault needs --native-lab-sspm manifest')
    if a.key_mode!='none' and not m.get('native_lab_power'):
        raise ValueError('Key mode needs --native-lab-power manifest')
    if a.thermal_fault!='none' and (not m.get('native_lab_thermal') or a.key_mode!='none'):
        raise ValueError('Thermal fault needs its own --native-lab-thermal run, without key fault modes')
    if a.thermal_fault_after_fresh and (a.thermal_fault=='none' or a.queue_mode!='cycle'):
        raise ValueError('Post-fresh fault requires --thermal-fault and --queue-mode cycle')
    if a.gauge_fault!='none' and (not m.get('native_lab_gauge') or a.thermal_fault!='none' or a.key_mode!='none'):
        raise ValueError('Gauge fault requires an isolated --native-lab-gauge run')
    if a.gauge_fault_after_valid and (a.gauge_fault=='none' or a.queue_mode!='cycle'):
        raise ValueError('Post-valid gauge fault requires --gauge-fault and --queue-mode cycle')
    if a.bif_fault!='none' and (not m.get('native_lab_bif') or a.thermal_fault!='none' or a.gauge_fault!='none' or a.key_mode!='none'):
        raise ValueError('BIF fault requires an isolated --native-lab-bif run')
    if a.bif_fault_after_fresh and (a.bif_fault=='none' or a.queue_mode!='cycle'):
        raise ValueError('Post-fresh BIF fault requires --bif-fault and --queue-mode cycle')
    if a.bif_clear_after_rejection and (a.bif_fault=='none' or a.bif_fault_after_fresh or a.queue_mode!='cycle' or a.expect_bif_rejected):
        raise ValueError('Fault clearing needs an isolated startup BIF fault and --queue-mode cycle')
    if a.expect_bif_rejected and (not m.get('native_lab_bif') or a.bif_fault_after_fresh):
        raise ValueError('BIF rejection check requires an explicitly malformed startup handoff')
    bif_fault_name=a.bif_fault if a.bif_fault=='adc-stale' else 'bif-'+a.bif_fault
    command=list(m['command'])
    if a.bif_fault!='none' and not a.bif_fault_after_fresh:
        command[command.index('-M')+1]+=',lab-power-fault='+bif_fault_name
    if a.gauge_fault!='none' and not a.gauge_fault_after_valid:
        command[command.index('-M')+1]+=',lab-power-fault=gauge-'+a.gauge_fault
    if a.thermal_fault!='none' and not a.thermal_fault_after_fresh:
        command[command.index('-M')+1]+=',lab-power-fault=thermal-'+a.thermal_fault
    if a.sspm_fault!='none':
        command[command.index('-M')+1]+=',lab-sspm-fault='+a.sspm_fault
    if a.display_fault!='none':
        command[command.index('-M')+1]+=',lab-display-fault='+a.display_fault
    out=a.manifest.resolve().parent
    socket_path=out/(a.label+'.qmp')
    if socket_path.exists():raise ValueError('QMP socket exists; choose another label')
    snapshots=[];injected=False;queue_enabled=False;cycle_disabled=False;proc=None;client=None;reader=None
    framebuffer_untouched=None
    thermal_injected=False;thermal_injected_at=None
    gauge_injected=False;gauge_injected_at=None
    bif_injected=False;bif_injected_at=None
    bif_cleared=False;bif_cleared_at=None;bif_rejection_before_clear=None
    key_pressed=False;key_released=False;key_started=0
    expected_buttons={1,2,3} if a.key_mode=='cycle' else {1} if a.key_mode=='power-fault' else {2,3}
    qemu_sha256=hashlib.sha256(Path(m['command'][0]).read_bytes()).hexdigest()
    serial_path=out/(a.label+'.serial.log')
    with serial_path.open('w') as serial:
        try:
            proc=subprocess.Popen(command+['-qmp',f'unix:{socket_path},server=on,wait=off'],stdout=serial,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+15
            while not socket_path.exists():
                if proc.poll() is not None:raise RuntimeError('QEMU exited before QMP')
                if time.monotonic()>deadline:raise TimeoutError('QMP startup timeout')
                time.sleep(.1)
            client=socket.socket(socket.AF_UNIX);client.settimeout(15);client.connect(str(socket_path));reader=client.makefile('rb')
            json.loads(reader.readline())
            def execute(cmd,**args):
                client.sendall(json.dumps({'execute':cmd,'arguments':args}).encode()+b'\n')
                while True:
                    r=json.loads(reader.readline())
                    if 'error' in r:raise RuntimeError(r)
                    if 'return' in r:return r['return']
            execute('qmp_capabilities');started=time.monotonic()
            while time.monotonic()-started<a.seconds:
                if proc.poll() is not None:raise RuntimeError('QEMU exited during native probe')
                state=json.loads(execute('qom-get',path='/machine',property='lab-i2c-state'))
                snapshot={'seconds':round(time.monotonic()-started,3),'state':state}
                if m.get('native_lab_display'):
                    snapshot['display']=json.loads(execute('qom-get',path='/machine',property='lab-display-state'))
                if m.get('native_lab_power'):
                    snapshot['power']=json.loads(execute('qom-get',path='/machine',property='lab-power-state'))
                if m.get('native_lab_sspm'):
                    snapshot['sspm']=json.loads(execute('qom-get',path='/machine',property='lab-sspm-state'))
                snapshots.append(snapshot)
                observed=serial_path.read_text(errors='replace') if a.queue_mode!='none' or a.key_mode!='none' else ''
                if a.queue_mode!='none' and not queue_enabled and 'MT6762_QUEUE_READY' in observed:
                    execute('qom-set',path='/machine',property='lab-touch-sequence',value=True)
                    queue_enabled=True
                bif_records=re.findall(r'MT6762_SYSCTL mt6762_bif_pair_fresh=(\d+) error=0',observed)
                if a.bif_fault_after_fresh and not bif_injected and bif_records and int(bif_records[-1])==1:
                    execute('qom-set',path='/machine',property='lab-power-fault',value=bif_fault_name)
                    bif_injected=True;bif_injected_at=round(time.monotonic()-started,3)
                if a.bif_clear_after_rejection and not bif_cleared:
                    rejected={name:int(value) for name,value in re.findall(
                        r'MT6762_SYSCTL (mt6762_bif_\w+)=(-?\d+) error=0',observed)}
                    if (rejected.get('mt6762_bif_errors',0)>0 and
                        rejected.get('mt6762_bif_pair_fresh')==0 and
                        rejected.get('mt6762_bif_raw')==-1 and
                        rejected.get('mt6762_bif_ntc_raw')==-1):
                        bif_rejection_before_clear={'native':rejected,'power_model':snapshot.get('power')}
                        execute('qom-set',path='/machine',property='lab-power-fault',value='none')
                        bif_cleared=True;bif_cleared_at=round(time.monotonic()-started,3)
                valid_records=re.findall(r'MT6762_SYSCTL mt6762_gauge_current_valid=(\d+) error=0',observed)
                if a.gauge_fault_after_valid and not gauge_injected and valid_records and int(valid_records[-1])==1:
                    execute('qom-set',path='/machine',property='lab-power-fault',value='gauge-'+a.gauge_fault)
                    gauge_injected=True;gauge_injected_at=round(time.monotonic()-started,3)
                fresh_records=re.findall(r'MT6762_SYSCTL mt6762_thermal_fresh=(\d+) error=0',observed)
                if a.thermal_fault_after_fresh and not thermal_injected and fresh_records and int(fresh_records[-1])==7:
                    execute('qom-set',path='/machine',property='lab-power-fault',value='thermal-'+a.thermal_fault)
                    thermal_injected=True;thermal_injected_at=round(time.monotonic()-started,3)
                if a.key_mode!='none' and not key_pressed and 'MT6762_QUEUE_READY' in observed:
                    mask=7 if a.key_mode=='cycle' else 1 if a.key_mode=='power-fault' else 6
                    execute('qom-set',path='/machine',property='lab-key-mask',value=mask)
                    key_pressed=True;key_started=time.monotonic()
                observed_buttons={int(n) for n in re.findall(r'MT6762_QUEUE type=4 finger=(\d+)',observed)}
                if key_pressed and not key_released and expected_buttons<=observed_buttons and time.monotonic()-key_started>.15:
                    if a.key_mode=='cycle':
                        execute('qom-set',path='/machine',property='lab-key-mask',value=0)
                    else:
                        execute('qom-set',path='/machine',property='lab-power-fault',value='stall' if a.key_mode=='power-fault' else 'keypad-disabled')
                    key_released=True
                if a.queue_mode=='fault' and not injected and 'MT6762_QUEUE type=2 ' in observed:
                    execute('qom-set',path='/machine',property='lab-i2c-fault',value='dma');injected=True
                if a.queue_mode=='cycle' and queue_enabled and not cycle_disabled and time.monotonic()-started>a.seconds-.3:
                    execute('qom-set',path='/machine',property='lab-touch-sequence',value=False);cycle_disabled=True
                if a.fault_after_dma_reads and not injected and state['i2c0']['dma_reads']>=a.fault_after_dma_reads:
                    execute('qom-set',path='/machine',property='lab-i2c-fault',value='dma');injected=True
                time.sleep(.01 if a.queue_mode!='none' or a.key_mode!='none' else .25)
            if m.get('framebuffer'):
                fb=m['framebuffer']; raw=out/(a.label+'.bgra')
                execute('stop')
                execute('pmemsave',val=fb['addr'],size=fb['size'],filename=str(raw))
                framebuffer_untouched=raw.read_bytes()==Path(fb['file']).read_bytes()
            execute('quit')
        finally:
            if reader:reader.close()
            if client:client.close()
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
    serial=serial_path.read_text(errors='replace')
    final=snapshots[-1]['state'] if snapshots else {}
    events=[{'type':int(t),'finger':int(f),'x':int(x),'y':int(y),'time':int(tm),'log_offset':match.start()}
        for match in re.finditer(r'MT6762_QUEUE type=(\d+) finger=(\d+) x=(\d+) y=(\d+) time=(\d+)',serial)
        for t,f,x,y,tm in [match.groups()]]
    held={};buttons_held=set();buttons_down=[];buttons_up=[];matched_releases=0;release_after_error=False
    error_offset=serial.find('stopped: transport error')
    for event in events:
        key=event['finger'];point=(event['x'],event['y'])
        if event['type']==4:
            buttons_held.add(key);buttons_down.append(key)
        elif event['type']==5:
            if key in buttons_held:buttons_up.append(key)
            buttons_held.discard(key)
        if event['type'] in (1,2):held[key]=point
        elif event['type']==3:
            if held.pop(key,None)==point:
                matched_releases+=1
                release_after_error |= error_offset>=0 and event['log_offset']>error_offset
    battery_observations=[]
    if m.get('native_lab_battery_gap_ms'):
        for block in re.findall(r'MT6762_SYSCTL_BEGIN(.*?)MT6762_SYSCTL_END',serial,re.S):
            observation={name:int(value) for name,value in re.findall(
                r'MT6762_SYSCTL (\w+)=(-?\d+) error=0',block)}
            fields=('mt6762_battery_report_gap_state','mt6762_battery_reports_suppressed',
                'mt6762_adc_voltage_requests','mt6762_power_valid','battery_voltage_mv',
                'battery_current_ma','battery_present','battery_charger_present',
                'battery_charging','battery_soc','battery_temperature_c')
            if all(k in observation for k in fields):
                battery_observations.append({k:observation[k] for k in fields})
    result={'synthetic_model_only':True,
            'synthetic_adc_delay_override_us':m.get('native_lab_adc_delay_us',0),'physical_hardware_tested':False,'kernel_sha256':m['kernel_sha256'],
            'qemu_binary_sha256':qemu_sha256,'synthetic_framebuffer_untouched':framebuffer_untouched,
            'native_display_accepted':'BGRA scanout verified; no panel reset' in serial,
            'display_startup_fault':a.display_fault,
            'native_brightness_accepted':'inherited DISP_PWM0 validated' in serial,
            'synthetic_display_state':snapshots[-1].get('display') if snapshots else None,
            'sspm_startup_fault':a.sspm_fault,
            'expected_bif_handoff_rejection':a.expect_bif_rejected,
            'bif_fault_cleared_after_rejection':bif_cleared,
            'bif_fault_cleared_at_seconds':bif_cleared_at,
            'bif_rejection_before_clear':bif_rejection_before_clear,
            'bif_startup_fault':a.bif_fault if not a.bif_fault_after_fresh else 'none',
            'bif_post_fresh_fault':a.bif_fault if a.bif_fault_after_fresh else 'none',
            'bif_fault_injected_after_fresh':bif_injected,'bif_fault_injected_at_seconds':bif_injected_at,
            'gauge_startup_fault':a.gauge_fault if not a.gauge_fault_after_valid else 'none',
            'gauge_post_valid_fault':a.gauge_fault if a.gauge_fault_after_valid else 'none',
            'gauge_fault_injected_after_valid':gauge_injected,'gauge_fault_injected_at_seconds':gauge_injected_at,
            'thermal_startup_fault':a.thermal_fault if not a.thermal_fault_after_fresh else 'none',
            'thermal_post_fresh_fault':a.thermal_fault if a.thermal_fault_after_fresh else 'none',
            'thermal_fault_injected_after_fresh':thermal_injected,
            'thermal_fault_injected_at_seconds':thermal_injected_at,
            'key_mode':a.key_mode, 'buttons_down':buttons_down,'buttons_matching_up':buttons_up,
            'buttons_held_at_end':sorted(buttons_held),
            'native_battery_publication_gap':dict(start_ms=m.get('native_lab_battery_gap_start_ms',0),
                duration_ms=m.get('native_lab_battery_gap_ms',0),observations=battery_observations),
            'native_power_accepted':'power: PMIC 0x5730' in serial,
            'synthetic_power_state':snapshots[-1].get('power') if snapshots else None,
            'native_sysctls':{name:{'value':int(value),'error':int(error)} for name,value,error in
                re.findall(r'MT6762_SYSCTL (\w+)=(-?\d+) error=(-?\d+)',serial)},
            'native_sspm_alive':'PLATFORM probe result=0 alive=1 fault=0' in serial,
            'synthetic_sspm_state':snapshots[-1].get('sspm') if snapshots else None,
            'native_i2c0_ready':'native I2C0 ready' in serial,'native_i2c5_ready':'native I2C5 ready' in serial,
            'touch_version_accepted':('MT6762_TOUCH_VERSION error=0 bytes=0007' in serial or
                                      'native consumer running' in serial),
            'touch_dma_reads':final.get('i2c0',{}).get('dma_reads',0),
            'charger_bus_transactions':final.get('i2c5',{}).get('transactions',0),
            'synthetic_psc_control':final.get('i2c5',{}).get('psc_control'),
            'synthetic_psc_status':final.get('i2c5',{}).get('psc_status'),
            'dma_fault_injected':injected,'touch_worker_stopped_on_error':'stopped: transport error' in serial,
            'kernel_panic_observed':'panic(' in serial,'queue_mode':a.queue_mode,
            'expected_cpu_count':m.get('cpu_count',1),
            'secondary_cpus_online':sorted(set(int(n) for n in re.findall(r'arm_cpu_init\(\): cpu (\d+) online',serial))),
            'queue_observer_ready':'MT6762_QUEUE_READY' in serial,
            'queue_downs':sum(e['type']==1 for e in events),'queue_moves':sum(e['type']==2 for e in events),
            'queue_ups':sum(e['type']==3 for e in events),'queue_matching_releases':matched_releases,
            'queue_matching_release_after_error':release_after_error,
            'queue_held_at_end':len(held),'queue_events':events,'snapshots':snapshots}
    (out/(a.label+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('snapshots','queue_events')},indent=2))
    if m.get('cpu_count',1)>1 and result['secondary_cpus_online']!=list(range(1,m['cpu_count'])):
        raise SystemExit(1)
    if a.expect_handoff_rejected:
        if (result['native_i2c0_ready'] or result['native_i2c5_ready'] or result['touch_version_accepted'] or
            result['touch_dma_reads'] or result['charger_bus_transactions'] or result['kernel_panic_observed'] or
            framebuffer_untouched is not True or 'No video - forcing serial' not in serial or
            'native scanout handoff rejected' not in serial):
            raise SystemExit(1)
        return
    if not result['native_i2c0_ready'] or not result['touch_version_accepted'] or not result['touch_dma_reads'] or result['kernel_panic_observed']:
        raise SystemExit(1)
    if a.key_mode!='none' and (not key_released or set(buttons_down)!=expected_buttons or set(buttons_up)!=expected_buttons or buttons_held):
        raise SystemExit(1)
    if m.get('native_lab_power') and not result['native_power_accepted']:
        raise SystemExit(1)
    if m.get('native_lab_battery_gap_ms'):
        before=[o for o in battery_observations if o['mt6762_battery_report_gap_state']==0 and
                o['mt6762_power_valid']&4 and o['battery_voltage_mv']==4400]
        expired=[o for o in battery_observations if o['mt6762_battery_report_gap_state']==1 and
                 o['mt6762_power_valid']==0]
        recovered=[o for o in battery_observations if o['mt6762_battery_report_gap_state']==2 and
                   o['mt6762_power_valid']&4 and o['battery_voltage_mv']==4400]
        unknown={'battery_voltage_mv':-1,'battery_current_ma':-2147483648,
                 'battery_present':-1,'battery_charger_present':-1,'battery_charging':-1}
        # Separate getters may cross a publication boundary; require repeated
        # coherent expiry observations, not equality for every read sequence.
        expired=[o for o in expired if all(o[k]==value for k,value in unknown.items())]
        if not before or len(expired)<2 or not recovered:
            raise SystemExit(1)
        if (expired[-1]['mt6762_adc_voltage_requests']<=expired[0]['mt6762_adc_voltage_requests'] or
            recovered[-1]['mt6762_battery_reports_suppressed']<1 or
            any(o['battery_soc']!=-1 or o['battery_temperature_c']!=-273 for o in battery_observations)):
            raise SystemExit(1)
    if a.bif_clear_after_rejection and not bif_cleared:
        raise SystemExit(1)
    if a.bif_fault_after_fresh and not bif_injected:
        raise SystemExit(1)
    if m.get('native_lab_bif'):
        diagnostic=result['native_sysctls']
        fields=['mt6762_bif_raw','mt6762_bif_ntc_raw','mt6762_bif_pair_fresh','mt6762_bif_samples','mt6762_bif_errors','mt6762_bif_fault']
        if any(name not in diagnostic or diagnostic[name]['error'] for name in fields):
            raise SystemExit(1)
        values={name:diagnostic[name]['value'] for name in fields}
        if result['synthetic_power_state']['bif_tdet_write_attempts']:
            raise SystemExit(1)
        if a.expect_bif_rejected:
            if result['synthetic_power_state']['bif_requests'] or values['mt6762_bif_fault']!=1 or values['mt6762_bif_errors']<1 or values['mt6762_bif_raw']!=-1 or values['mt6762_bif_ntc_raw']!=-1 or values['mt6762_bif_pair_fresh']:
                raise SystemExit(1)
        elif a.bif_fault=='none' or (bif_cleared and a.bif_fault in ('stale','adc-stale')):
            if values['mt6762_bif_raw']!=4089 or values['mt6762_bif_ntc_raw']!=1400 or values['mt6762_bif_pair_fresh']!=1 or values['mt6762_bif_samples']<1:
                raise SystemExit(1)
        elif values['mt6762_bif_raw']!=-1 or values['mt6762_bif_ntc_raw']!=-1 or values['mt6762_bif_pair_fresh']:
            raise SystemExit(1)
        if bif_cleared:
            retryable=a.bif_fault in ('stale','adc-stale')
            if values['mt6762_bif_fault'] != (0 if retryable else 1):
                raise SystemExit(1)
            if retryable and (bif_rejection_before_clear['native'].get('mt6762_bif_last_error')!=-5 or
                              bif_rejection_before_clear['native'].get('mt6762_bif_generation_rejections',0)<1):
                raise SystemExit(1)
    if a.bif_fault=='adc-stale' and not bif_cleared:
        diagnostic=result['native_sysctls']
        if diagnostic['mt6762_battery_adc_mv']['value']!=-1 or diagnostic['mt6762_ntc_adc_mv']['value']!=-1 or diagnostic['mt6762_power_valid']['value']&4:
            raise SystemExit(1)
    if a.gauge_fault_after_valid and not gauge_injected:
        raise SystemExit(1)
    if m.get('native_lab_gauge'):
        diagnostic=result['native_sysctls']
        fields=['mt6762_gauge_current_ua','mt6762_gauge_current_valid','mt6762_gauge_samples','mt6762_gauge_fault']
        if any(name not in diagnostic or diagnostic[name]['error'] for name in fields):
            raise SystemExit(1)
        values={name:diagnostic[name]['value'] for name in fields}
        if a.gauge_fault=='none':
            if values['mt6762_gauge_current_ua']!=a.expected_gauge_current_ua or values['mt6762_gauge_current_valid']!=1 or values['mt6762_gauge_samples']<2 or values['mt6762_gauge_fault']:
                raise SystemExit(1)
        elif values['mt6762_gauge_current_ua']!=-2147483648 or values['mt6762_gauge_current_valid']:
            raise SystemExit(1)
    if a.expect_gauge_charge:
        if not m.get('native_lab_gauge'):
            raise ValueError('Charge validation requires the native gauge fixture')
        diagnostic=result['native_sysctls']
        fields=('mt6762_gauge_charge_uah','mt6762_gauge_charge_valid')
        if any(name not in diagnostic or diagnostic[name]['error'] for name in fields):
            raise SystemExit(1)
        # Expected signed value comes from an independent original-stock vector.
        expected=(a.expected_gauge_charge_uah,1) if a.gauge_fault=='none' else (-(1<<63),0)
        if tuple(diagnostic[name]['value'] for name in fields)!=expected:
            raise SystemExit(1)
    if a.thermal_fault_after_fresh and not thermal_injected:
        raise SystemExit(1)
    if m.get('native_lab_thermal'):
        diagnostic=result['native_sysctls']
        fields=['mt6762_pmic_die_mc','mt6762_pmic_buck1_mc','mt6762_pmic_buck2_mc',
                'mt6762_thermal_observed','mt6762_thermal_fresh','mt6762_thermal_samples','mt6762_thermal_errors','mt6762_cpu_ts1_mc']
        if any(name not in diagnostic or diagnostic[name]['error'] for name in fields):
            raise SystemExit(1)
        values={name:diagnostic[name]['value'] for name in fields}
        if values['mt6762_cpu_ts1_mc']!=-273000:
            raise SystemExit(1)
        if a.thermal_fault=='none':
            if values['mt6762_thermal_fresh']!=7 or values['mt6762_thermal_observed']!=7 or values['mt6762_thermal_samples']<3:
                raise SystemExit(1)
        elif a.thermal_fault=='mux':
            fresh=values['mt6762_thermal_fresh'];observed=values['mt6762_thermal_observed']
            if fresh&~6 or observed&~6 or values['mt6762_pmic_die_mc']!=-273000:
                raise SystemExit(1)
            if any(values[fields[i]]!=-273000 for i in (1,2) if not observed&(1<<i)):
                raise SystemExit(1)
        elif values['mt6762_thermal_fresh'] or values['mt6762_thermal_observed'] or any(values[name]!=-273000 for name in fields[:3]):
            raise SystemExit(1)
    if m.get('native_lab_sspm'):
        state=result['synthetic_sspm_state']
        if state['dvfs_emulated'] or state['rejected_commands']:
            raise SystemExit(1)
        if a.sspm_fault=='none':
            if not (result['native_sspm_alive'] and state['requests'] and state['responses'] and state['ack_clears']):
                raise SystemExit(1)
        elif result['native_sspm_alive']:
            raise SystemExit(1)
        if a.sspm_fault in ('stale-ack','stale-input') and (state['requests'] or state['data_writes'] or state['control_writes']):
            raise SystemExit(1)
    if m.get('native_lab_display'):
        if a.display_fault=='none':
            if not (result['native_display_accepted'] and result['native_brightness_accepted']):
                raise SystemExit(1)
        elif (result['native_display_accepted'] or result['native_brightness_accepted'] or
              result['synthetic_display_state']['pwm_writes'] or framebuffer_untouched is not True or
              'power/clocks/OVL0/DSI readback mismatch' not in serial):
            raise SystemExit(1)
    if a.fault_after_dma_reads and not (injected and result['touch_worker_stopped_on_error']):
        raise SystemExit(1)
    if a.queue_mode!='none' and not (result['queue_downs'] and result['queue_moves'] and matched_releases):
        raise SystemExit(1)
    if a.queue_mode=='fault' and not (injected and release_after_error and not held):
        raise SystemExit(1)
    if a.queue_mode=='cycle' and held:
        raise SystemExit(1)

if __name__=='__main__':main()
