"""Measure only ERMCLIP processes. Save CPU/RAM and device-wide GPU evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import psutil

ROOT=Path(__file__).resolve().parents[1]

def owned_processes():
    ids=set()
    for record in ('health.json','local-model.json','desktop-window.json'):
        try:
            data=json.loads((ROOT/'state'/record).read_text())
            p=psutil.Process(data['pid'])
            if record=='local-model.json' and abs(p.create_time()-data['created'])>.01:
                continue
            cmd=' '.join(p.cmdline()).lower()
            if record=='health.json' and ('ermclip' not in cmd or 'worker' not in cmd):
                continue
            if record=='desktop-window.json' and 'launch-ermclip.py' not in cmd:
                continue
            ids.add(p.pid)
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
    # Identify the loopback app, not arbitrary Python/browser processes.
    for p in psutil.process_iter(['pid','cmdline']):
        try:
            cmd=' '.join(p.info['cmdline'] or []).lower()
            own_app='-m ermclip.webapp' in cmd and Path(p.cwd()).resolve()==ROOT
            if own_app or ('-m http.server' in cmd and str(ROOT/'output').lower() in cmd):
                ids.add(p.pid)
        except psutil.Error:
            pass
    for pid in tuple(ids):
        try:
            ids.update(p.pid for p in psutil.Process(pid).children(recursive=True))
        except psutil.Error:
            pass
    result={}
    for pid in ids:
        try:
            p=psutil.Process(pid)
            cpu=p.cpu_times()
            mem=p.memory_info()
            result[pid]={'pid':pid,'name':p.name(),'created':p.create_time(),
                         'cpu_seconds':cpu.user+cpu.system,'working_set_mib':round(mem.rss/2**20,2),
                         'private_mib':round(getattr(mem,'private',mem.vms)/2**20,2)}
        except psutil.Error:
            pass
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',required=True)
    parser.add_argument('--seconds',type=float,default=15)
    args=parser.parse_args()
    before=owned_processes();start=time.monotonic();time.sleep(args.seconds);after=owned_processes();elapsed=time.monotonic()-start
    cpu=sum(max(0,item['cpu_seconds']-before[pid]['cpu_seconds']) for pid,item in after.items() if pid in before and before[pid]['created']==item['created'])
    gpu=subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10)
    report={'label':args.label,'time':time.time(),'interval_seconds':round(elapsed,2),'logical_cpus':psutil.cpu_count(),
            'cpu_percent_of_machine':round(cpu/elapsed/psutil.cpu_count()*100,3),
            'cpu_percent_one_core':round(cpu/elapsed*100,3),
            'working_set_mib':round(sum(p['working_set_mib'] for p in after.values()),2),
            'private_mib':round(sum(p['private_mib'] for p in after.values()),2),
            'processes':list(after.values()),'gpu_device_wide_csv':gpu.stdout.strip(),
            'notes':'GPU is the whole device, including unrelated apps. Working set sum can count shared pages twice. CPU uses processes present in both snapshots.'}
    path=ROOT/'output/workspace-checks'/f'{args.label}.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
