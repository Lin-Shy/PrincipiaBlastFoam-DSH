"""Probe process-wide read isolation before invoking the ordinary DSH entry point."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import win32api
import win32con
import win32event
import win32process
import win32security as security
import ntsecuritycon
from test_read_permissions_fixture import grant_fixture

WS=Path(__file__).resolve().parents[5]
NODE=WS/".chapter3-runtime/stage-20261117/bin/node.exe"
DRIVER=WS/"PrincipiaBlastFoam-DSH/experiments/end2end/integrated_dev/driver.mjs"


def main():
    results=[]
    with tempfile.TemporaryDirectory(prefix="dsh-process-read-") as tmp:
        base=Path(tmp)
        for arm in ("general","professional"):
            work=base/arm/"workspace"
            work.mkdir(parents=True)
            (base/arm/"parent.txt").write_text("harmless",encoding="ascii")
            exe=work/"node.exe"
            shutil.copyfile(NODE,exe)
            script=work/"probe.cjs"
            script.write_text("require('node:fs').writeFileSync('started.json',JSON.stringify({started:true}));",encoding="ascii")
            sid=security.ConvertStringSidToSid("S-1-5-21-314159-271828-161803-"+str(1001+len(results)))
            for p in (work,exe,script):
                grant_fixture(p,sid,ntsecuritycon.FILE_GENERIC_READ|ntsecuritycon.FILE_GENERIC_EXECUTE|ntsecuritycon.FILE_GENERIC_WRITE)
            token=security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_ALL_ACCESS)
            restricted=security.CreateRestrictedToken(token,1,[],[],[(sid,0)])
            for label,tok in (("unrestricted",token),("read_restricted",restricted)):
                marker=work/"started.json"
                marker.unlink(missing_ok=True)
                try:
                    proc,thread,pid,tid=win32process.CreateProcessAsUser(tok,str(exe),subprocess.list2cmdline([str(exe),str(script)]),None,None,False,win32con.CREATE_NO_WINDOW,dict(os.environ),str(work),win32process.STARTUPINFO())
                    wait=win32event.WaitForSingleObject(proc,20000)
                    if wait==win32con.WAIT_TIMEOUT:
                        win32process.TerminateProcess(proc,1)
                        win32event.WaitForSingleObject(proc,5000)
                    code=win32process.GetExitCodeProcess(proc)
                    proc.Close()
                    thread.Close()
                    results.append(dict(arm=arm,mode=label,exit_code=code,exit_hex=hex(code & 0xffffffff),javascript_started=marker.exists()))
                except Exception as exc:
                    results.append(dict(arm=arm,mode=label,error_type=type(exc).__name__,winerror=getattr(exc,"winerror",None),javascript_started=marker.exists()))
            restricted.Close()
            token.Close()
    print(json.dumps(dict(node_sha256=__import__("hashlib").sha256(NODE.read_bytes()).hexdigest(),
         target_entry=str(DRIVER.relative_to(WS)),process_probe=results,model_requests=0,cluster_jobs=0),indent=2))


if __name__=="__main__":
    main()

