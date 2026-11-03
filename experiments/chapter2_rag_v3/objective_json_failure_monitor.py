"""Refresh failed-task rerun progress and audit only after complete closure."""
import subprocess
import sys
import time
from pathlib import Path
import objective_experiment as exp
import objective_json_failure_rerun as run

HERE=Path(__file__).resolve().parent


def call(script,*args):
    return subprocess.run([sys.executable,str(HERE/script),*args],capture_output=True,text=True,encoding='utf8',errors='replace')


def main():
    old=-1;unchanged=0
    while True:
        result=call('objective_json_failure_rerun.py','report')
        if result.returncode:
            exp.save(run.OUT/'monitor.json',dict(status='report_error',error=result.stderr[-2000:]));return 1
        snapshot=exp.read(run.OUT/'results/snapshot.json');done=snapshot['completed']
        if snapshot['status']=='closed':
            check=call('objective_json_failure_audit.py')
            if check.returncode:
                exp.save(run.OUT/'monitor.json',dict(status='audit_error',error=check.stderr[-2000:]));return 1
            exp.save(run.OUT/'monitor.json',dict(status='audited',completed=done,note='Manuscript, PDF visual review and Git delivery remain.'));return 0
        unchanged=unchanged+1 if done==old else 0
        exp.save(run.OUT/'monitor.json',dict(status='running' if unchanged<20 else 'stalled',completed=done,planned=snapshot['planned']))
        if unchanged>=20:return 2
        old=done;time.sleep(45)


if __name__=='__main__':raise SystemExit(main())
