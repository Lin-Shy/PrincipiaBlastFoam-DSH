import copy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_activity_costs import audit,measurements,summarize


def proxy(status='response',usage=None):
    return dict(provider='qwen_proxy',model='qwen3-8b',transport_attempts=1,content_retries=0,status=status,seconds=3,raw_response=dict(usage=usage) if usage else None)


def write(root,relative,row):
    p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(row),encoding='utf-8');return p


def test_missing_usage_is_unknown_and_failed_attempts_remain():
    result=summarize(measurements(proxy('transport_error'))+measurements(proxy(usage=dict(prompt_tokens=5,completion_tokens=7))))
    assert result['physical_attempts']==2 and result['usage_unknown_attempts']==1
    assert result['known_prompt_tokens']==5 and result['sum_known_request_seconds']==6
    assert result['money_cost'] is None


def test_custom_sse_top_level_usage_is_charged_once():
    row=proxy();row['usage']=dict(prompt_tokens=10,completion_tokens=20)
    assert summarize(measurements(row))['known_completion_tokens']==20


def test_offline_events_keep_failed_unknown_attempt_and_missing_duration():
    row=dict(request=dict(model='deepseek-flash'),events=[dict(attempt=1,status='transport_error'),dict(attempt=2,status='response',seconds=2,usage=dict(prompt_tokens=4,completion_tokens=6))])
    r=summarize(measurements(row))
    assert r['physical_attempts']==2 and r['usage_unknown_attempts']==1 and r['duration_unknown_attempts']==1


def test_copied_archive_and_continuation_receipt_not_recharged(tmp_path):
    row=proxy();rel='sessions/model/q/requests/00.json'
    write(tmp_path,'development/qa_001_scores/'+rel,row)
    write(tmp_path,'development/qa_001_scores_continued_002/'+rel,row)
    write(tmp_path,'audit/copy/'+rel,row)
    write(tmp_path,'archives/raw/'+rel,row)
    r=audit(tmp_path)
    assert r['total']['physical_attempts']==1 and len(r['byte_identical_copied_receipts_not_recharged'])==1


def test_conflicting_copy_is_rejected(tmp_path):
    write(tmp_path,'development/qa_001_scores/sessions/q/requests/00.json',proxy())
    row=proxy();row['seconds']=4
    write(tmp_path,'development/qa_001_scores_continued_002/sessions/q/requests/00.json',row)
    with pytest.raises(ValueError,match='Conflicting copied'):audit(tmp_path)


def test_live_request_cannot_be_a_complete_cost_result(tmp_path):
    write(tmp_path,'formal/generation_001/main/x/sessions/q/requests/00.json',proxy('in_flight'))
    with pytest.raises(ValueError,match='Live request'):audit(tmp_path)
    r=audit(tmp_path,True)
    assert r['total']['physical_attempts']==0 and len(r['in_flight_receipts_excluded'])==1


def test_unclassified_receipt_cannot_silently_disappear(tmp_path):
    write(tmp_path,'formal/new_unclassified/requests/00.json',proxy())
    with pytest.raises(ValueError,match='Unclassified'):audit(tmp_path)


def test_offline_and_probe_costs_have_separate_stages(tmp_path):
    write(tmp_path,'diagnosis/proxy_synthetic/model/request.json',proxy())
    row=dict(request=dict(model='deepseek-flash'),events=[dict(attempt=1,status='response',seconds=1)])
    write(tmp_path,'diagnosis/evaluation_only/rubric/sessions/q/responses/verify.json',row)
    r=audit(tmp_path)
    assert set(r['stages'])=={'offline_semantic_audit','operational_probes'}
    assert r['total']['physical_attempts']==2
