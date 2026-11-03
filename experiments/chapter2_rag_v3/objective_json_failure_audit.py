"""Verify failed-task recovery, scoring and paired statistics from source records."""
import csv
from collections import Counter, defaultdict
from pathlib import Path
import objective_experiment as exp
import objective_json_failure_rerun as run
import objective_json_strict as strict
from objective_statistics import analyze


def main():
    run.use(); m=exp.verify();out=run.OUT;snap_path=out/'results/snapshot.json'
    snap=exp.read(snap_path);rows=exp.read(out/'scores/per_answer.json')
    questions=exp.read(exp.DATA/'model/questions.json')
    gold={g['id']:g for g in exp.read(exp.DATA/'scoring/annotations.json')}
    reused={(x['config_id'],x['id']):x for x in exp.read(out/'reuse_inventory.json')}
    rerun={(x['config_id'],x['id']):x for x in exp.read(out/'rerun_inventory.json')}
    indexed={(r['config_id'],r['id']):r for r in rows}
    if snap['status']!='closed' or len(indexed)!=m['tasks'] or len(rows)!=m['tasks'] or set(reused)&set(rerun):
        raise ValueError('Incomplete or duplicate task inventory')
    new_sha=exp.sha(out/'manifest.json');recovered=0;valid=0;by_source=defaultdict(Counter)
    for c in m['configurations']:
        for q in questions:
            key=(c['config_id'],q['id']);path=out/'generation'/key[0]/key[1]/'result.json'
            r=exp.read(path);source=(reused if key in reused else rerun)[key]
            parent=run.PARENT/'generation'/key[0]/key[1]/'result.json'
            if exp.sha(parent)!=source['source_sha256'] or exp.read(parent)['status']!=source['source_status']:
                raise ValueError('Parent receipt changed')
            if key in reused:
                if exp.sha(path)!=source['source_sha256'] or source['source_status']!='answered':raise ValueError('Reused answer changed')
            else:
                if r['manifest_sha256']!=new_sha or source['source_status']=='answered':raise ValueError('Rerun identity mismatch')
                recovered+=int(r['status']=='answered')
                valid+=int(indexed[key]['format_valid'] is True)
                by_source[source['source_status']][r['status']]+=1
            for field,value in strict.score(q,gold[q['id']],r).items():
                if indexed[key].get(field)!=value:raise ValueError('Scoring mismatch '+str(key)+' '+field)
    for c in m['configurations']:
        group=[r for r in rows if r['config_id']==c['config_id']]
        summary=next(s for s in snap['configurations'] if s['config_id']==c['config_id'])
        if summary['correct']!=sum(r['score'] for r in group) or summary['accuracy']!=sum(r['score'] for r in group)/len(questions):raise ValueError('Summary mismatch')
    if analyze(rows,m['analysis'])!=snap['statistics']:raise ValueError('Statistics mismatch')
    for name,expected in [('per_answer.csv',rows),('summary.csv',snap['configurations'])]:
        with (out/'results'/name).open(encoding='utf-8-sig',newline='') as f:exported=list(csv.DictReader(f))
        if len(exported)!=len(expected):raise ValueError('CSV row count mismatch')
        for a,b in zip(exported,expected):
            if any(a[k]!=('' if v is None else str(v)) for k,v in b.items()):raise ValueError('CSV content mismatch')
    exp.save(out/'results/json_audit.json',dict(status='passed',tasks=len(rows),reused=len(reused),rerun=len(rerun),
        rerun_answered=recovered,rerun_format_valid=valid,snapshot_sha256=exp.sha(snap_path),manifest_sha256=new_sha,
        outcomes_by_original_status={k:dict(v) for k,v in sorted(by_source.items())},
        audit_code_sha256=exp.sha(Path(__file__))))
    print('Failure recovery audit passed:',len(rows),'tasks;',recovered,'recovered answers;',valid,'format-valid')


if __name__=='__main__':main()
