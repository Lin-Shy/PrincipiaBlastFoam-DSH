"""1400-row synthetic failure grid; no LLM requests and no real result edits."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from common import *

def test_full_synthetic_failed_grid_preserves_denominator(tmp_path,monkeypatch):
    import score_round2
    import analyze_e2e
    from chapter2_formal_scoring_200 import failed_generation
    config=score_round2.CONFIG;p=read(config);gen=tmp_path/'generation';scoring=tmp_path/'scoring';out=tmp_path/'analysis'
    bindings={};qs=public_questions()
    for arm in p['arms']:
        sealed=[];arm_bindings={}
        for q in qs:
            qid=q['id'];path=gen/arm/'generation'/qid/'result.json'
            save(path,dict(id=qid,arm=arm,status='transport_error',delivered_lines=[],tool_events=[],references=None,
                counted_input_tokens=10,actual_completion_tokens=0,turns=[{}],knowledge_characters=0,seconds=.1))
            row=dict(arm=arm,id=qid,generation_sha256=sha(path),generation_status='transport_error');sealed.append(row)
            scorepath=scoring/'sessions'/arm/qid/'result.json'
            save(scorepath,{**failed_generation('transport_error'),'arm':arm,'id':qid,'generation_sha256':sha(path),'execution_protocol_sha256':sha(config)})
            arm_bindings[qid]=bindings[f'{arm}/{qid}']=sha(scorepath)
        sealpath=scoring/'sealed_arms'/(arm+'.json');save(sealpath,dict(rows=sealed))
        save(scoring/'completed_arms'/(arm+'.json'),dict(sealed_arm_sha256=sha(sealpath),results_sha256=arm_bindings))
    save(scoring/'completion.json',dict(sessions=1400,execution_protocol_sha256=sha(config),results_sha256=bindings))
    monkeypatch.setattr(score_round2,'audit_generation',lambda *args:dict(passed=True))
    analyze_e2e.analyze(gen,scoring,out)
    summary=read(out/'summary.json')
    assert summary['sessions']==1400
    assert len(read(out/'session-metrics.json'))==1400
    assert all(v['n']==200 and v['score_lower']==v['score_upper']==v['complete_upper']==0 for v in summary['by_arm'].values())
    assert summary['judge']['request_statuses']=={}
    assert len(summary['comparisons']['main'])==4
    assert len(summary['comparisons']['new_ablations'])==2
    assert all(v['holm_p_upper']==1 for xs in summary['comparisons'].values()for v in xs)
