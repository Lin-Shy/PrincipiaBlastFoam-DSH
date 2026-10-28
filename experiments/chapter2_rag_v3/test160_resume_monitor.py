"""Wait for the authorized Windows scoring processes; audit only after they drain.

Does not send model requests, alter scoring, or publish incomplete final results.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time
import single_pass_dev40 as s

def run(pids):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handles={pid:kernel.OpenProcess(0x1000,False,pid) for pid in pids}
    out=s.RUN/'test160_runs/reconnect_monitor.json'
    try:
        while True:
            states={}
            for pid,handle in handles.items():
                code=wintypes.DWORD()
                if not handle:states[str(pid)]='not_found'
                elif kernel.GetExitCodeProcess(handle,ctypes.byref(code)):states[str(pid)]='running' if code.value==259 else int(code.value)
                else:raise OSError(ctypes.get_last_error(),'Cannot query scoring process')
            s.save(out,dict(utc=s.now(),state='waiting',workers=states,formal_statistics_published=False))
            if 'running' not in states.values():break
            time.sleep(15)
        logfile=s.RUN/'test160_runs/reconnect_audit.stdout.log'
        with logfile.open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('test160_closure_audit.py'))],stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        summary=s.load(s.RUN/'test160_runs/closure_audit.json') if result.returncode==0 else {}
        s.save(out,dict(utc=s.now(),state='audited' if result.returncode==0 else 'audit_failed',workers=states,audit_exit_code=result.returncode,
           answered=summary.get('answered'),dual_valid=summary.get('dual_valid'),missing_dual=summary.get('missing_dual'),
           formal_experiment_complete=summary.get('formal_experiment_complete',False),formal_statistics_published=False,
           next_step='Recompute statistics and refresh manuscript from the drained audit; preserve any unresolved protocol holds.'))
    finally:
        for handle in handles.values():
            if handle:kernel.CloseHandle(handle)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pids',nargs='+',type=int,required=True);run(p.parse_args().pids)
