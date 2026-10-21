"""Post-result metric alternatives; no rejudgment or original-score changes."""
import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict
from chapter2_optimization_200 import read,save,sha


def graded_validity(row):
    """Retain partial coverage, but retain the original truth/condition gates."""
    fact=row['factuality']
    flo=int(fact=='pass');fhi=int(fact in {'pass','unknown'})
    alo=row['condition_lower'] if row['conditional'] else 1
    ahi=row['condition_upper'] if row['conditional'] else 1
    return row['coverage_lower']*flo*alo,row['coverage_upper']*fhi*ahi


def valid_at_threshold(row,threshold):
    if not 0<threshold<=1:raise ValueError('Threshold outside (0,1]')
    fact=row['factuality']
    alo=row['condition_lower'] if row['conditional'] else 1
    ahi=row['condition_upper'] if row['conditional'] else 1
    return (int(row['coverage_lower']+1e-12>=threshold)*int(fact=='pass')*alo,
            int(row['coverage_upper']+1e-12>=threshold)*int(fact in {'pass','unknown'})*ahi)


def main(source,output):
    if output.exists():raise FileExistsError(output)
    rows=read(source/'session-metrics.json');summary=read(source/'summary.json')
    assert len(rows)==len({(r['arm'],r['id']) for r in rows})==1400
    derived=[];by=defaultdict(list)
    for r in rows:
        lo,hi=graded_validity(r)
        strict=valid_at_threshold(r,1)
        assert strict==(r['cv_lower'],r['cv_upper']),'Original metric must be exactly recovered at threshold1'
        if r['generation_status']!='answered':assert lo==hi==0
        assert 0<=r['cv_lower']<=lo<=hi<=1
        d={k:r[k] for k in ['arm','id','group','type']}
        d.update(graded_validity_lower=lo,graded_validity_upper=hi,
            original_strict_lower=r['cv_lower'],original_strict_upper=r['cv_upper'])
        for label,threshold in [('50',.5),('75',.75),('80',.8),('100',1)]:
            l,u=valid_at_threshold(r,threshold)
            d.update({f'valid_at_{label}_lower':l,f'valid_at_{label}_upper':u})
        by[r['arm']].append(d);derived.append(d)
    arms={}
    for arm,rs in by.items():
        assert len(rs)==200
        keys=[k for k in rs[0] if k.endswith(('_lower','_upper'))]
        arms[arm]=dict(n=200,**{k:sum(r[k] for r in rs)/200 for k in keys})
        groups=defaultdict(list)
        for r in rs:groups[r['group']].append(r)
        arms[arm].update({f'knowledge_group_macro_{k}':sum(sum(r[k] for r in group)/len(group) for group in groups.values())/len(groups) for k in ['graded_validity_lower','graded_validity_upper']})
        for side in ['lower','upper']:
            assert abs(arms[arm]['original_strict_'+side]-summary['by_arm'][arm]['complete_'+side])<1e-12
    result=dict(schema='post_result_end_to_end_metric_options_v1',status='discussion_only_not_adopted',
        source_summary_sha256=sha(source/'summary.json'),source_sessions_sha256=sha(source/'session-metrics.json'),
        implementation_sha256=sha(Path(__file__)),original_primary_unchanged=True,new_model_calls=0,
        proposed_graded_validity=dict(name='端到端有效回答得分',
            formula='Mean_i[required_point_coverage_i * factual_validity_i * condition_validity_i], scaled to0-100 points',
            coverage='Final answer semantic necessary-point coverage:full1,partial0.5,missing/wrong0',
            fact='Original frozen factuality:pass1,fail0,unknown[0,1]; no evaluation after generation failure0',
            condition='Original applicable-condition validity; non-condition questions1; pass1,fail/generation_failure0,unknown[0,1]',
            boundary='A graded end-to-end answer score, not a success rate or retrieval score. Keeps strict truth/condition gates; partial correctness can earn credit. Bounds conservatively propagate unknowns.'),
        threshold_options=dict(name='达标有效回答率',formula='Mean_i[coverage_i>=tau AND factual_validity_i AND condition_validity_i]',
            exploratory_thresholds=[.5,.75,.8,1],threshold_selected=False,
            boundary='Any adopted threshold needs a task-based rationale. These are post-result sensitivity calculations, not preregistered confirmation; do not pick a threshold to maximize an observed gap.'),
        all_200_per_arm=arms,
        validation='All1400 scores exactly reproduce original strict CV at tau=1; generation failures remain0; no unknowns dropped, no rescoring or rewritten judgments',
        interpretation='Changing the aggregation need not improve the system or establish statistical superiority; acceptance remains pending user discussion.')
    save(output/'summary.json',result)
    save(output/'sessions.json',derived)
    with (output/'summary.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['arm',*next(iter(arms.values()))]);writer.writeheader()
        for arm,r in arms.items():writer.writerow(dict(arm=arm,**r))
    print(json.dumps(arms,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.source,a.output)
