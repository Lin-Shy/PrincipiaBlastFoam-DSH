"""Synthetic figure QA, isolated from formal results and all Test scores."""
from copy import deepcopy
from pathlib import Path
import json
import test160_report as report
from judge_contract import calculate


def run():
    dest=report.s.WORKSPACE/'.local/test160-report-qa'
    dest.mkdir(parents=True,exist_ok=True)
    report.OUT=dest
    ids=['fixture_'+x for x in ['S0','S1','M0','M1']]
    maps={k:{q:q for q in ids} for k in ['linked','fact','theme','knowledge']}
    rows=[]
    for mode in ['agentic','single_pass']:
        for model in report.MODELS:
            for method in report.METHODS if mode=='agentic' else ['graph','bm25','bge_m3']:
                for q in ids:
                    typ=q.split('_')[1];conditional=typ.endswith('1')
                    score=calculate([.75],.75,.75 if conditional else 'not_applicable',conditional)
                    base=75-report.METHODS.index(method)*2+(5 if mode=='single_pass' else 0)
                    score.update(EAS_arith=base,EAS_geo=base,eas_arith_bounds=[base,base],eas_geo_bounds=[base,base])
                    rows.append(dict(mode=mode,model=model,method=method,question_id=q,type=typ,conditional=conditional,
                         knowledge_group=q,theme=q,linked_cluster=q,generation_status='answered',generation_failed=False,evaluation_complete=True,
                         score=dict(composite={k:report.number(score.get(k)) for k in ['K','F','A','EAS_arith','EAS_geo']},
                                    bounds={k:[base,base] for k in report.METRICS},by_judge={j:deepcopy(score) for j in report.s.JUDGES},unknown_items=0,missing_items=0),
                         strict_bounds=[0,0],evidence=dict(line_recall=.7,complete=False,evidence_span_recall=.5),
                         tool_calls=2 if mode=='agentic' else 0,backend_search_calls=1,characters=4000,tool_errors=0,
                         actual_prompt_tokens=1000,actual_completion_tokens=200,physical_generation_requests=2,
                         usage_missing_responses=0,seconds=12))
    policy=report.s.load(report.s.RUN/'release/protocol/test160_analysis.json')
    policy['bootstrap_resamples']=100
    groups=[]
    for mode in ['agentic','single_pass']:
        for model in report.MODELS:
            for method in report.METHODS if mode=='agentic' else ['graph','bm25','bge_m3']:
                groups.append(report.summary([r for r in rows if (r['mode'],r['model'],r['method'])==(mode,model,method)],maps,policy))
    paired,questions=report.comparisons(rows,maps,policy)
    assert len(paired)==60
    files=report.figures(groups,paired,rows)
    assert len(files)==18 and all(p.stat().st_size>1000 for p in files)
    (dest/'validation.json').write_text(json.dumps(dict(synthetic_only=True,real_test_scores_read=False,figures=18,comparisons=60),indent=2),encoding='utf-8')
    print(dest)


if __name__=='__main__':run()
