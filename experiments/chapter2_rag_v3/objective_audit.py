"""Audit a closed objective experiment against source records and frozen rules."""
from collections import Counter
from pathlib import Path
import objective_experiment as experiment
from objective_scoring import score

def main():
    manifest=experiment.verify()
    questions=experiment.read(experiment.DATA/'model/questions.json')
    gold={g['id']:g for g in experiment.read(experiment.DATA/'scoring/annotations.json')}
    scores=experiment.read(experiment.OUT/'scores/per_answer.json')
    snapshot=experiment.read(experiment.OUT/'results/snapshot.json')
    if snapshot['status']!='closed' or snapshot['completed']!=manifest['tasks']:
        raise ValueError('closed complete snapshot required')
    records={(r['config_id'],r['id']):r for r in scores}
    if len(records)!=manifest['tasks'] or len(scores)!=len(records):raise ValueError('missing or duplicate scored task')
    errors=[]; statuses=Counter(); n=0
    for config in manifest['configurations']:
        for question in questions:
            key=(config['config_id'],question['id'])
            result_file=experiment.OUT/'generation'/key[0]/key[1]/'result.json'
            if key not in records or not result_file.is_file():errors.append([*key,'missing']);continue
            result=experiment.read(result_file); row=records[key]
            if result.get('manifest_sha256')!=experiment.sha(experiment.MANIFEST):errors.append([*key,'manifest_mismatch'])
            expected=score(question,gold[key[1]],result)
            for field in ('score','reason','normalized_answer','format_valid','scoring_version'):
                if row[field]!=expected[field]:errors.append([*key,'scoring_mismatch:'+field])
            statuses[result['status']]+=1;n+=1
    groups={r['config_id']:r for r in snapshot['configurations']}
    for config in manifest['configurations']:
        key=config['config_id']; subset=[r for r in scores if r['config_id']==key]
        expected=sum(r['score'] for r in subset)/len(questions)
        if len(subset)!=len(questions) or abs(groups[key]['accuracy']-expected)>1e-12:
            errors.append([key,'summary_mismatch'])
    audit=dict(status='passed' if not errors else 'failed',planned=manifest['tasks'],audited=n,
               terminal_statuses=dict(statuses),errors=errors,
               manifest_sha256=experiment.sha(experiment.MANIFEST),
               snapshot_sha256=experiment.sha(experiment.OUT/'results/snapshot.json'),
               per_answer_sha256=experiment.sha(experiment.OUT/'scores/per_answer.json'),
               code_sha256=experiment.sha(Path(__file__)))
    experiment.save(experiment.OUT/'results/closure_audit.json',audit)
    print('closure audit:',audit['status'],'audited',n,'/',manifest['tasks'])
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
