from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common import *
import human_review_round2 as review
import qa_outputs
import pytest

def test_new_blinded_answers_bind_fixed_sample_and_raw_new_answers():
    forms=read(review.OUT/'blinded_answers.json');keys=read(review.OUT/'evaluation_only/method_key.json')
    old=read(ARCHIVE/'human_review/sampling_manifest.json')
    assert len(forms)==80 and {f['question_id']for f in forms}==set(old['question_ids'])
    for f,k in zip(forms,keys):
        assert f['sample_id']==k['sample_id']and f['question_id']==k['question_id']
        r=read(WORKSPACE/k['answer_file'])
        assert f['raw_answer']==r['answer']and sha(WORKSPACE/k['answer_file'])==k['answer_sha256']
        assert not {'arm','model','score','judgment'}&set(f)

def test_pending_reviews_do_not_claim_human_accuracy(monkeypatch,tmp_path):
    monkeypatch.setattr(review,'ARCHIVE',tmp_path)
    review.aggregate(review.OUT/'ratings_template.json','pending')
    result=read(tmp_path/'reports/pending/human_summary.json')
    assert result['completed']==0 and result['submitted_pending']==160
    assert result['inter_human']['points']is None and result['ai_human']=='pending real human labels'

def test_invalid_completed_human_labels_rejected(monkeypatch,tmp_path):
    monkeypatch.setattr(review,'ARCHIVE',tmp_path)
    ratings=read(review.OUT/'ratings_template.json');ratings[0]['review_status']='complete'
    path=tmp_path/'bad.json';save(path,ratings)
    with pytest.raises(ValueError):review.aggregate(path,'bad')
    assert not(tmp_path/'reports/bad').exists()

def test_ai_eas_retains_unknown_gate_and_failure_zero():
    m=dict(required_point_coverage_lower=.5,required_point_coverage_upper=1,factuality='unknown',applicability='pass')
    assert review.ai_eas(m,True)==(0,100)
    m['factuality']='pass';m['applicability']='fail'
    assert review.ai_eas(m,True)==(0,0)
    assert review.ai_eas(m,False)==(50,100)

def test_case_selection_reports_wins_losses_and_evidence_counterexample():
    rows=[]
    for arm in qa_outputs.MAIN:
        for qid,g,b,eg,eb in [('A',1,0,1,0),('B',0,1,1,0)]:
            s=g if arm=='graph'else b;e=eg if arm=='graph'else eb
            rows.append(dict(arm=arm,id=qid,score_lower=s,score_upper=s,necessary_evidence_recall=e))
    cases=qa_outputs.case_ids(rows)
    assert {c['selection']for c in cases}=={'graph_win','text_win','more_evidence_lower_score'}
    assert all(c['id']=='B'for c in cases if c['selection']=='more_evidence_lower_score')

def test_usage_counts_physical_receipts_and_keeps_unknown(tmp_path,monkeypatch):
    monkeypatch.setattr(qa_outputs,'WORKSPACE',tmp_path)
    a=tmp_path/'a.json';b=tmp_path/'b.json'
    save(a,dict(status='response',response=dict(usage=dict(prompt_tokens=10,completion_tokens=2,total_tokens=12))))
    save(b,dict(status='transport_error'))
    result,bindings=qa_outputs.receipt_usage([a,b])
    assert result['requests']==2 and result['known_token_subtotals']['total_tokens']==12 and result['unknown_usage_requests']==1
    assert len(bindings)==2
