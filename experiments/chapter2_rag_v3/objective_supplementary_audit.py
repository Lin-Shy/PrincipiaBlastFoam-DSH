"""Independently verify supplementary parse scores against original results."""
from pathlib import Path
import objective_experiment as exp
from objective_scoring_relaxed import score

def main():
    manifest=exp.verify();out=exp.OUT/'supplementary_parser'
    snapshot=exp.read(out/'results/snapshot.json');rows=exp.read(out/'scores/per_answer.json')
    if snapshot['status']!='closed' or snapshot['completed']!=manifest['tasks']:raise ValueError('closed snapshot required')
    qs={q['id']:q for q in exp.read(exp.DATA/'model/questions.json')}
    gs={g['id']:g for g in exp.read(exp.DATA/'scoring/annotations.json')}
    strict={(r['config_id'],r['id']):r for r in exp.read(exp.OUT/'scores/per_answer.json')}
    seen=set();errors=[]
    for row in rows:
        key=(row['config_id'],row['id'])
        if key in seen:errors.append([*key,'duplicate'])
        seen.add(key)
        raw=exp.read(exp.OUT/'generation'/key[0]/key[1]/'result.json')
        expected=score(qs[key[1]],gs[key[1]],raw)
        for name in ('score','reason','normalized_answer','format_valid','parse_route','scoring_version'):
            if row[name]!=expected[name]:errors.append([*key,name])
        if row['strict_score']!=strict[key]['score'] or row['strict_reason']!=strict[key]['reason']:
            errors.append([*key,'strict_reference'])
    if len(seen)!=manifest['tasks']:errors.append(['task_count'])
    audit=dict(status='failed' if errors else 'passed',count=len(seen),errors=errors,
        snapshot_sha256=exp.sha(out/'results/snapshot.json'),per_answer_sha256=exp.sha(out/'scores/per_answer.json'),
        code_sha256=exp.sha(Path(__file__)))
    exp.save(out/'results/closure_audit.json',audit)
    print('supplementary closure audit:',audit['status'],len(seen))
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
