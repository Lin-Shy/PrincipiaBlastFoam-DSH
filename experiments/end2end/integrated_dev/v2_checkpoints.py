"""Operator-side checkpoint inventory; never infer a checkpoint from the final ZIP."""
import hashlib
import json
import zipfile
from pathlib import Path
from b11_live import batch,sha,write

def collect(task,arm):
    r=batch/'local_live'/task/arm
    if not (r/'sealed.json').exists():return
    rec=json.loads((r/'sealed.json').read_bytes())
    original=batch/'work'/arm/task/'first/input'
    source_hashes={sha(f) for f in original.rglob('*.py')}
    def inventory(items):
        scripts=[n for n,h in items.items() if n.endswith('.py') and h not in source_hashes]
        delivery=[n for n in items if n.startswith('delivery/')]
        return dict(new_or_changed_python=scripts,delivery_files=delivery)
    if rec['requests']<32:early={'status':'未达到'}
    else:
        log=r/'checkpoint32.json';zpath=r/'checkpoint32.zip'
        meta=json.loads(log.read_bytes()) if log.exists() else {}
        if zpath.exists() and sha(zpath)==meta.get('sha256'):
            with zipfile.ZipFile(zpath) as z:
                early=inventory({n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()})
            early.update(status='实测',archive_sha256=sha(zpath))
        else:early={'status':'未知'}
    ws=r/'workspace';final=inventory({f.relative_to(ws).as_posix():sha(f) for f in ws.rglob('*') if f.is_file()})
    assert sha(r/'submission.zip')==rec['archive_sha256']
    final.update(archive_sha256=rec['archive_sha256'],sealed_delivery_files=list(rec['files']))
    out=batch/'local_reviews'/task;out.mkdir(exist_ok=True,parents=True)
    path=out/(arm+'.v2_boundaries.json')
    if not path.exists():write(path,dict(request32=early,final=final))

if __name__=='__main__':
    for task,arm in [('B21','professional'),('B22','general'),('B22','professional'),('C03','general'),('C03','professional')]:
        collect('CH3-DEV-'+task,arm)
