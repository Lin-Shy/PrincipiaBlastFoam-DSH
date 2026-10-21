import hashlib
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_knowledge_stage_costs import reconcile, event_rows


def record(root,name,start='2026-10-15T07:00:00+00:00',status='response',known=True):
    body=dict(model='Qwen3-14B',messages=[dict(role='user',content='sample')])
    value=dict(provider='qwen_local',model=body['model'],endpoint='http://127.0.0.1:8001/v1/chat/completions',
        transport_attempts=1,content_retries=0,started_utc=start,status=status,request=body,
        request_sha256=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    if status!='in_flight':value['seconds']=2
    if known:value['raw_response']=dict(usage=dict(prompt_tokens=10,completion_tokens=3))
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
    return path,value


def test_native_local_http_and_copied_response_are_counted_once(tmp_path):
    _,value=record(tmp_path,'development/local_score_calibration_004/requests/00.json')
    p=tmp_path/'audit/local_qwen_transition_001/copy/requests/00.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(value))
    r=reconcile(tmp_path)
    assert r['grand_total']['physical_attempts']==1 and r['grand_total']['known_total_tokens']==13
    assert r['duplicate_physical_events_not_recharged']==1
    assert r['stages']['local_primary_scoring_development']['physical_attempts']==1
    assert r['stages']['local_migration_diagnostics']['physical_attempts']==0


def test_same_body_at_new_start_is_a_new_physical_local_attempt(tmp_path):
    record(tmp_path,'formal_scores_local_004/cell/requests/00.json')
    record(tmp_path,'formal_scores_local_004/cell/requests/01.json',start='2026-10-15T07:00:01+00:00')
    r=reconcile(tmp_path)
    assert r['stages']['formal_local_primary_grading']['physical_attempts']==2
    assert r['stages']['formal_primary_grading']['physical_attempts']==0


def test_local_transport_timeout_usage_is_unknown_not_zero(tmp_path):
    record(tmp_path,'development/local_actual_answer_audit_004/requests/00.json',status='transport_error',known=False)
    r=reconcile(tmp_path)['grand_total']
    assert r['physical_attempts']==1 and r['usage_unknown_attempts']==1 and r['known_total_tokens']==0


def test_interrupted_local_start_is_not_fabricated_as_terminal(tmp_path):
    record(tmp_path,'development/local_score_calibration_002/requests/00.json',status='in_flight',known=False)
    r=reconcile(tmp_path)['grand_total']
    assert r['unresolved_attempt_starts']==1 and r['duration_unknown_attempts']==1 and r['usage_unknown_attempts']==1


def test_conflicting_copies_of_local_usage_are_rejected(tmp_path):
    _,value=record(tmp_path,'development/local_score_calibration_004/requests/00.json')
    value['raw_response']['usage']['completion_tokens']=4
    p=tmp_path/'audit/local_qwen_transition_001/copy/requests/00.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='conflicting'):reconcile(tmp_path)


@pytest.mark.parametrize('change',[dict(transport_attempts=2),dict(started_utc='2026-10-15T07:00:00'),dict(endpoint='http://x/v1/chat/completions?key=hidden')])
def test_invalid_local_identity_fails_instead_of_guessing(tmp_path,change):
    path,value=record(tmp_path,'formal_scores_local_004/cell/requests/00.json');value.update(change);path.write_text(json.dumps(value))
    with pytest.raises(ValueError):event_rows(path,tmp_path)


def test_quality_and_gold_files_are_not_opened_when_collecting_native_local_costs(tmp_path,monkeypatch):
    record(tmp_path,'formal_scores_local_004/cell/requests/00.json')
    p=tmp_path/'formal_scores_local_004/cell/score.json';p.write_text('not a ledger')
    original=Path.read_bytes
    def checked(path):
        if path.name=='score.json':pytest.fail('opened quality label')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',checked)
    assert reconcile(tmp_path)['request_record_files']==1
