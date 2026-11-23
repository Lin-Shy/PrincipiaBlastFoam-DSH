"""Recreate matrix and summary using reviewed README commands and sealed node data."""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from check_delivery import verify
from pair import PAIR,read,write


def replay(arm,commands,case_path,summary_path,continuation=False):
    root = PAIR/arm
    segment = root/"continuation" if continuation else root
    checks = verify(arm,continuation)
    work = segment/"review_replay"
    delivery = work/"delivery"
    delivery.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(segment/"submission.zip") as z:
        for name in z.namelist():
            if Path(name).name in {"case.json","summary.json"}:
                continue
            target = delivery/name
            if Path(name).is_absolute() or not target.resolve().is_relative_to(delivery.resolve()):
                raise ValueError("unsafe ZIP path")
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(z.read(name))
        expected_summary = json.loads(z.read(next(n for n in z.namelist() if Path(n).name=="summary.json")))
    logs = []
    for cwd,args in commands:
        result = subprocess.run([sys.executable,*args],cwd=work/cwd,capture_output=True,timeout=60)
        logs.append(dict(cwd=cwd,argv=["python",*args],exit=result.returncode,
                         stdout=result.stdout.decode(errors="replace"),stderr=result.stderr.decode(errors="replace")))
    case = work/case_path
    summary = work/summary_path
    matrix_ok = case.exists() and read(case)==read(root/"operator/input/case.json")
    summary_ok = summary.exists() and read(summary)==expected_summary
    full = all(log["exit"]==0 for log in logs) and matrix_ok and summary_ok and checks["numerical_pass"] and checks["readme_present"]
    write(segment/"review.json",dict(verdict="complete" if full else "partial",checks=checks,
          reproduced_matrix=matrix_ok,reproduced_summary=summary_ok,commands=logs))
    return full
