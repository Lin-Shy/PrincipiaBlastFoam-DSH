"""Operator-side numerical evidence, only for fully sealed pairs; no agent calls."""
import csv
import hashlib
import io
import itertools
import json
import math
import sys
import zipfile
from pathlib import Path
from b11_live import WS,batch,base,sha

def table(data):
    reader=csv.reader(io.StringIO(data.decode('utf-8-sig')))
    header=next(reader)
    rows=[list(map(float,row)) for row in reader if row]
    if not rows or not all(len(row)==len(header) and all(map(math.isfinite,row)) for row in rows):raise ValueError('invalid numeric table')
    return header,list(zip(*rows))

def match(ref,got):
    head,cols=ref;other,values=got
    if len(cols[0])!=len(values[0]):return None
    selected=[]
    for col in cols:
        candidates=[]
        for i,val in enumerate(values):
            error=max(abs(a-b) for a,b in zip(val,col))
            if error<=1e-8:candidates.append((i,error))
        selected.append(candidates)
    for combo in itertools.product(*selected):
        if len({i for i,_ in combo})==len(combo):
            return {name:{'candidate':other[i],'max_abs':error} for name,(i,error) in zip(head,combo)}

def inspect(task):
    assignments = json.loads((batch/'attempts.json').read_bytes())
    records = {}
    for assignment in assignments:
        if assignment['id'] != task:
            continue
        state = json.loads((batch/assignment['status_file']).read_bytes())
        if not state.get('run_evidence'):
            return
        receipt = batch/state['run_evidence']
        rec = json.loads(receipt.read_bytes())
        if state.get('submission'):
            archive = batch/state['submission']
        else:
            archive = receipt.with_name('submission.zip')
        if rec['archive_sha256'] != sha(archive):
            raise ValueError(f'changed sealed archive for {task}/{assignment["system"]}')
        records[assignment['system']] = (rec, archive)
    if set(records) != {'general', 'professional'}:
        return
    taskrow=next(r for r in json.loads((batch/'tasks.json').read_bytes()) if r['id']==task)
    grading=(batch/taskrow['grading_zip']).resolve();assert sha(grading)==taskrow['grading_sha256']
    out=batch/'local_reviews'/task;out.mkdir(parents=True,exist_ok=True)
    if (out/'tables.json').exists():return
    with zipfile.ZipFile(grading) as z:
        refs={f:table(z.read(f)) for f in z.namelist() if f.endswith('.csv') and f in ['baseline.csv','expected_changed.csv']}
        checks=z.read('CHECKS.md').decode('utf-8-sig')
    result={}
    for arm,(rec,archive) in records.items():
        candidate={};matches={key:{} for key in refs}
        with zipfile.ZipFile(archive) as z:
            for f in z.namelist():
                data=z.read(f);assert hashlib.sha256(data).hexdigest()==rec['files'][f]
                if not f.lower().endswith('.csv'):continue
                try:parsed=table(data)
                except (ValueError,UnicodeError,StopIteration):continue
                candidate[f]={'columns':parsed[0],'rows':len(parsed[1][0])}
                for key,ref in refs.items():
                    matching=match(ref,parsed)
                    if matching:matches[key][f]=matching
        result[arm]=dict(files=list(rec['files']),tables=candidate,numeric_matches=matches)
    with (out/'tables.json').open('x',encoding='utf-8') as stream:json.dump(dict(task=task,checks=checks,arms=result),stream,ensure_ascii=False,indent=2)

if __name__=='__main__':
    for row in json.loads((batch/'attempts.json').read_bytes()):
        if row['system']=='general' and not row['proposed_cluster_jobs']:inspect(row['id'])
