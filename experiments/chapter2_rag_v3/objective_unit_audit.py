"""Verify explicit-unit scoring fallback against every frozen objective result."""
from pathlib import Path
import objective_experiment as exp
from objective_scoring import score as frozen
from objective_scoring_units import score as unit_score, VERSION

def main():
    manifest=exp.verify();out=exp.OUT
    questions=exp.read(exp.DATA/'model/questions.json')
    gold={x['id']:x for x in exp.read(exp.DATA/'scoring/annotations.json')}
    if any('answer_unit' in g for g in gold.values()):raise ValueError('Unexpected unit metadata: review required')
    snapshot=exp.read(out/'results/snapshot.json')
    if snapshot['status']!='closed' or snapshot['completed']!=manifest['tasks']:raise ValueError('closed snapshot required')
    records={(x['config_id'],x['id']):x for x in exp.read(out/'scores/per_answer.json')}
    mismatches=[];checked=0
    for c in manifest['configurations']:
        for q in questions:
            key=(c['config_id'],q['id']);result=exp.read(out/'generation'/key[0]/key[1]/'result.json')
            original=frozen(q,gold[q['id']],result);extended=unit_score(q,gold[q['id']],result)
            if original!=extended or any(original[k]!=records[key][k] for k in ('raw_answer','score','reason','normalized_answer','format_valid','scoring_version')):
                mismatches.append(list(key))
            checked+=1
    if checked!=manifest['tasks'] or mismatches:raise ValueError('score mismatch: '+str(mismatches[:5]))
    audit={'status':'passed','checked':checked,'numeric_items':sum(bool(g.get('numeric')) for g in gold.values()),
           'items_with_unit_metadata':0,'unit_rule_activated':0,'interpretation':'Frozen dataset explicitly requires original units without suffix; unit conversion is a separately versioned capability only when sourced unit metadata exists.',
           'manifest_sha256':exp.sha(exp.MANIFEST),'strict_scores_sha256':exp.sha(out/'scores/per_answer.json'),
           'rule_version':VERSION,'unit_code_sha256':exp.sha(Path(__file__).with_name('objective_scoring_units.py')),
           'audit_code_sha256':exp.sha(Path(__file__))}
    exp.save(out/'analysis/unit_extension_audit.json',audit)
    print('unit extension fallback audit passed:',checked,'tasks')

if __name__=='__main__':main()
