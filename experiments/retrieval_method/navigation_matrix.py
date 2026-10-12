"""并行调度独立冻结运行；只恢复同一传输请求，不重采样已提交答案。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def read(path):return json.loads(path.read_text())
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def retryable(run):
    reports=sorted(run.glob('run-status-*.json'))
    if not reports:return False
    errors=read(reports[-1]).get('errors',[])
    if not errors or any(not e.get('reason','').startswith('transport_error;') for e in errors):return False
    for error in errors:
        for path in (run/'sessions'/error['session']).glob('*.json'):
            row=read(path)
            if any(e.get('http_status') in (400,401,402,403) for e in row.get('events',[])):return False
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('run','replay','verify'))
    p.add_argument('--runs',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--key-file',type=Path)
    p.add_argument('--workers-per-run',type=int,default=1)
    p.add_argument('--max-rounds',type=int,default=3)
    a=p.parse_args();a.runs=[r.resolve() for r in a.runs]
    if len(a.runs)!=len(set(a.runs)):raise ValueError('duplicate run would race')
    if a.command=='run' and not a.key_file:raise ValueError('run needs a key file')
    a.output.mkdir(parents=True,exist_ok=False);shutil.copy2(__file__,a.output/'driver.py')
    identity={'command':a.command,'runs':{str(r):sha(r/'protocol.json') for r in a.runs},
        'driver_sha256':sha(a.output/'driver.py'),'workers_per_run':a.workers_per_run,'maximum_parallel_runs':len(a.runs),
        'max_transport_rounds':a.max_rounds,'resumption':'Only saved identical transport requests; no retry of received invalid answers or quality failures.',
        'timing_limitation':'Concurrent conditions share CPU and provider load; this is not an independent repeated latency benchmark.'}
    save(a.output/'matrix.json',identity)
    def execute(run):
        records=[]
        for i in range(1,a.max_rounds+1):
            cmd=[sys.executable,str(run/'runner.py'),a.command,'--run',str(run),'--workers',str(a.workers_per_run)]
            if a.command=='run':cmd+=['--key-file',str(a.key_file.resolve())]
            start=time.monotonic()
            proc=subprocess.run(cmd,capture_output=True,text=True)
            (a.output/f'{run.name}-round-{i}.log').write_text(proc.stdout+proc.stderr)
            records.append({'round':i,'exit_code':proc.returncode,'wall_seconds':time.monotonic()-start})
            save(a.output/f'{run.name}.json',{'run':str(run),'rounds':records})
            print(run.name,'round',i,'exit',proc.returncode,flush=True)
            if proc.returncode==0 or a.command!='run' or not retryable(run):break
        return {'run':str(run),'ok':records[-1]['exit_code']==0,'rounds':records}
    with ThreadPoolExecutor(max_workers=len(a.runs)) as pool:result=list(pool.map(execute,a.runs))
    save(a.output/'results.json',result)
    if any(not row['ok'] for row in result):raise SystemExit(1)


if __name__=='__main__':main()
