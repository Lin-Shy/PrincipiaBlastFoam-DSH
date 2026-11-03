"""Reconstruct scores and verify both sides of an endpoint transition."""
import csv
from pathlib import Path
import objective_experiment as exp
import objective_json_transition as transition
import objective_json_strict as strict
from objective_statistics import analyze


def main():
    transition.use_transition()
    m = exp.verify()
    out = transition.OUT
    snapshot = out/'results/snapshot.json'
    snap = exp.read(snapshot); rows = exp.read(out/'scores/per_answer.json')
    questions = exp.read(exp.DATA/'model/questions.json')
    gold = {x['id']:x for x in exp.read(exp.DATA/'scoring/annotations.json')}
    reused = {(x['config_id'], x['id']):x for x in exp.read(out/'reuse_inventory.json')}
    unknown = {(x['config_id'], x['id']) for x in exp.read(out/'unknown_inventory.json')}
    indexed = {(r['config_id'],r['id']):r for r in rows}
    if snap['status'] != 'closed' or len(indexed) != m['tasks'] or len(rows) != m['tasks']:
        raise ValueError('Results not closed or duplicated')
    new_sha = exp.sha(out/'manifest.json')
    for c in m['configurations']:
        for q in questions:
            key = c['config_id'],q['id']
            path = out/'generation'/key[0]/key[1]/'result.json'
            record = exp.read(path)
            if key in reused:
                if exp.sha(path) != reused[key]['source_sha256'] or record['manifest_sha256'] != m['parent_manifest_sha256']:
                    raise ValueError('Reused result or parent identity changed')
            elif record['manifest_sha256'] != new_sha:
                raise ValueError('Transition result identity changed')
            if key in unknown and record['status'] != 'unknown_request_state':
                raise ValueError('Unknown task must remain an unknown failure')
            for field, value in strict.score(q, gold[q['id']], record).items():
                if indexed[key].get(field) != value:
                    raise ValueError(f'Score mismatch: {key}, {field}')
    for c in m['configurations']:
        group = [r for r in rows if r['config_id'] == c['config_id']]
        summary = next(s for s in snap['configurations'] if s['config_id'] == c['config_id'])
        if summary['correct'] != sum(r['score'] for r in group) or summary['accuracy'] != sum(r['score'] for r in group)/len(questions):
            raise ValueError('Summary mismatch')
    if analyze(rows, m['analysis']) != snap['statistics']:
        raise ValueError('Statistics mismatch')
    for name, expected in [('per_answer.csv', rows), ('summary.csv', snap['configurations'])]:
        with (out/'results'/name).open(encoding='utf-8-sig', newline='') as f:
            exported = list(csv.DictReader(f))
        if len(exported) != len(expected):
            raise ValueError('CSV count mismatch')
        for a,b in zip(exported,expected):
            if any(a[k] != ('' if v is None else str(v)) for k,v in b.items()):
                raise ValueError('CSV content mismatch')
    exp.save(out/'results/json_audit.json', dict(status='passed', tasks=len(rows), reused=len(reused), unknown=len(unknown),
             snapshot_sha256=exp.sha(snapshot), manifest_sha256=new_sha, audit_code_sha256=exp.sha(Path(__file__))))
    print('Endpoint transition audit passed:',len(rows))


if __name__ == '__main__': main()
