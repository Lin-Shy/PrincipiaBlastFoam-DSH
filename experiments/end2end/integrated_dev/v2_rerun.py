"""Replay a reviewed Python entry using a fresh copy, never the live workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from b11_live import batch,sha,write

def replay(task,arm,when,entry,products,args,extras=(),label=None,entry_dir=False):
    r=batch/'local_live'/task/arm
    assert (r/'sealed.json').is_file()
    check=batch/'local_reviews'/task/f'{arm}.{label or when}.replay'
    check.mkdir(exist_ok=False,parents=True)
    original=batch/'work'/arm/task/'first/input'
    work=check/'workspace';shutil.copytree(original,work)
    archive=r/('checkpoint32.zip' if when=='32' else 'submission.zip')
    wanted={}
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            relative=name if when=='32' else 'delivery/'+name
            dest=(work/relative).resolve()
            assert dest.is_relative_to(work.resolve())
            if relative in products:wanted[relative]=hashlib.sha256(z.read(name)).hexdigest()
            elif (relative.endswith('.py') or relative.endswith('/calibration.csv') or relative==entry or relative in extras):
                dest.parent.mkdir(exist_ok=True,parents=True);dest.write_bytes(z.read(name))
    for name in products:(work/name).parent.mkdir(exist_ok=True,parents=True)
    env={k:os.environ[k] for k in ['SystemRoot','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','LOCALAPPDATA'] if k in os.environ}
    env['MPLCONFIGDIR']=str(check.resolve()/'mpl-cache')
    command=(['pwsh','-NoProfile','-File'] if entry.endswith('.ps1') else [sys.executable,'-B','-X','utf8'])
    cwd=work/Path(entry).parent if entry_dir else work
    target=str((work/entry).resolve())
    if entry.endswith('.bat'):
        command=['cmd.exe','/d','/c']
    run=subprocess.run([*command,target,*args],cwd=cwd,env=env,capture_output=True,timeout=60)
    (check/'stdout.log').write_bytes(run.stdout);(check/'stderr.log').write_bytes(run.stderr)
    got={n:sha(work/n) for n in products if (work/n).is_file()}
    result=dict(archive_sha256=sha(archive),entry=entry,args=args,exit=run.returncode,sealed=wanted,replayed=got,
        equal=run.returncode==0 and len(wanted)==len(products) and wanted==got)
    write(check/'result.json',result);print(result['exit'],result['equal'])

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['task','arm','when','entry','products']:parser.add_argument(name)
    parser.add_argument('args',nargs=argparse.REMAINDER)
    a=parser.parse_args()
    replay(a.task,a.arm,a.when,a.entry,a.products.split(';'),a.args)
