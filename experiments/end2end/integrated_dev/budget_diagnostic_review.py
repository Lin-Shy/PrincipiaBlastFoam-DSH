"""Offline review of sealed, content-addressed deliveries. No DSH or model."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import zipfile
from budget_diagnostic import dest, batch, read, sha, write
from local_sealed_tables import table, match

def inventory(task,arm):
    root=dest/task/arm
    sealed=read(root/'sealed.json')
    assert sha(root/'submission.zip')==sealed['archive_sha256']
    assert read(root/'observer/final.json')==sealed['files']
    out=dest/'reviews'/task/arm
    out.mkdir(parents=True,exist_ok=True)
    package=next(r for r in read(batch/'tasks.json') if r['id']==task)
    grade=batch/package['grading_zip']
    assert sha(grade)==package['grading_sha256']
    with zipfile.ZipFile(grade) as z:
        refs={n:table(z.read(n)) for n in ('baseline.csv','expected_changed.csv')}
    labels=[f'before-{i}' for i in range(1,sealed['requests']+1)]
    if sealed['requests']>=32:labels.insert(32,'request32')
    cache={};last=None;history=[]
    for label in [*labels,'final']:
        value=read(root/'observer'/(label+'.json'))
        if value==last and label not in ('request32','final'):continue
        numerical={}
        for name,h in value.items():
            if not name.lower().endswith('.csv'):continue
            if h not in cache:
                blob=root/'observer/blobs'/h
                assert sha(blob)==h
                try:parsed=table(blob.read_bytes())
                except (ValueError,StopIteration,UnicodeError):parsed=None
                cache[h]={k:m for k,ref in refs.items() if parsed and (m:=match(ref,parsed))}
            if cache[h]:numerical[name]=cache[h]
        history.append(dict(label=label,changes=[n for n in set(value)|set(last or {}) if value.get(n)!=(last or {}).get(n)],numerical=numerical))
        last=value
    write(out/'inventory.json',history)

def replay(task,arm,label,variant,folder,products,command):
    root=dest/task/arm
    assert (root/'sealed.json').exists()
    observed=read(root/'observer'/(label+'.json'))
    out=dest/'reviews'/task/arm/(label+'-'+variant)
    work=out/'workspace';delivery=work/'delivery'
    delivery.mkdir(parents=True,exist_ok=False)
    for name,h in observed.items():
        target=(delivery/name).resolve()
        assert target.is_relative_to(delivery.resolve())
        data=root/'observer/blobs'/h
        assert sha(data)==h
        if name not in products:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data.read_bytes())
    if variant.startswith('public'):
        import shutil
        shutil.copytree(batch/'work'/arm/task/'first/input',work,dirs_exist_ok=True)
    env={k:os.environ[k] for k in ('SystemRoot','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','LOCALAPPDATA') if k in os.environ}
    done=subprocess.run(command,cwd=work/folder,env=env,capture_output=True,timeout=90)
    (out/'stdout.log').write_bytes(done.stdout);(out/'stderr.log').write_bytes(done.stderr)
    got={n:sha(delivery/n) for n in products if (delivery/n).is_file()}
    expected={n:observed.get(n) for n in products}
    result=dict(label=label,variant=variant,cwd=folder,command=command,exit=done.returncode,
        generated=got,expected=expected,equal=done.returncode==0 and got==expected)
    write(out/'result.json',result);print(done.returncode,result['equal'])

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('task');p.add_argument('arm');p.add_argument('extra',nargs=argparse.REMAINDER)
    a=p.parse_args()
    if not a.extra:inventory(a.task,a.arm)
    else:
        when,variant,folder,products,*command=a.extra
        replay(a.task,a.arm,when,variant,folder,products.split(';'),command)
