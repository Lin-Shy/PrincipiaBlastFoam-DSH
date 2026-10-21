"""No-network checks for the independent scoring execution adapter."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from common import *
from score_round2 import audit_generation,verify
from chapter2_metric_revision_200 import graded_validity,valid_at_threshold
from chapter2_formal_scoring_200 import failed_generation,unidentified
from chapter2_judge_200_rubric import requests
from chapter2_answer_scoring import scoring_payload
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus

def test_real_generation_receipt_audit():
    root=ARCHIVE/'e2e_runs/answer14b_001/graph/generation'
    source=next(root.glob('*/result.json'))
    q=next(q for q in public_questions()if q['id']==source.parent.name)
    assert audit_generation(source.parent,q['question'],'graph',read(ARCHIVE/'configs/e2e_14b_v1.json'),{})['passed']

def test_question_tampering_rejected():
    source=next((ARCHIVE/'e2e_runs/answer14b_001/graph/generation').glob('*/result.json'))
    with pytest.raises(ValueError,match='question changed'):
        audit_generation(source.parent,'tampered','graph',read(ARCHIVE/'configs/e2e_14b_v1.json'),{})

@pytest.mark.parametrize('factuality,condition,expected',[
    ('pass','pass',(.5,.5)),('fail','pass',(0,0)),('pass','fail',(0,0)),('unknown','pass',(0,.5)),('pass','unknown',(0,.5))])
def test_eas_gates(factuality,condition,expected):
    row=dict(factuality=factuality,conditional=True,coverage_lower=.5,coverage_upper=.5,
        condition_lower=int(condition=='pass'),condition_upper=int(condition in {'pass','unknown'}))
    assert graded_validity(row)==expected
    assert valid_at_threshold(row,1)==(0,0)

def test_failure_unknown_bounds():
    assert failed_generation('transport_error')['metrics']['complete_upper']==0
    assert unidentified('judge_failure')['metrics']['complete_upper']==1

def test_anonymous_payload_and_request():
    q=public_questions()[0];a=next(a for a in read(DATASET/'scoring/annotations.json')if a['id']==q['id'])
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    payload=scoring_payload(q['question'],a,read(DATASET/'scoring/evidence.json'),corpus,'不知道。')
    assert set(payload)=={'question','answer','rubric','original_material'}
    assert not {'arm','model','id'}&set(payload)
    reqs=requests(payload)
    assert len(reqs)==len(a['required_points'])+1
    assert all(r['body']['model']=='qwen3-14b'and r['body']['enable_thinking']is False for r in reqs)

def test_unapproved_scoring_rejected(tmp_path,monkeypatch):
    import score_round2
    protocol=tmp_path/'p.json';approval=tmp_path/'a.json'
    save(protocol,{'sessions':1400});save(approval,{'approved':False})
    monkeypatch.setattr(score_round2,'CONFIG',protocol)
    with pytest.raises(PermissionError):verify(approval)
