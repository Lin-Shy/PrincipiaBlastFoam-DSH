"""验证丢失客户端的显式结案，不改变语义评分或重发请求。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_local_score_interruption import interrupted_record, validate_interruption_observation, has_unknown_interruption_duration
from chapter2_local_judge_costs import physical_local_cost
from chapter2_local_compact_score_execution import request_sha
from chapter2_knowledge_stage_costs import local_event_rows, add_event, empty_totals, event_rows


def original():
    body={'model':'Qwen3-14B'}
    return dict(provider='qwen_local',status='in_flight',transport_attempts=1,content_retries=0,
        endpoint='http://localhost:8001/v1/chat/completions',model='Qwen3-14B',request=body,
        request_sha256=request_sha(body),started_utc='2026-10-15T22:00:00+00:00')


def close(record=None):
    return interrupted_record(record or original(),original_sha256='a'*64,
        observation_relative_path='audit/interruption.json',observation_sha256='b'*64,
        observed_utc='2026-10-15T22:01:00+00:00')


def test_closure_preserves_original_identity_and_does_not_fabricate_usage_or_duration():
    old=original(); before=deepcopy(old); new=close(old)
    assert old==before and new['request']==old['request']
    for k in ('request_sha256','started_utc','transport_attempts','content_retries','endpoint'):assert new[k]==old[k]
    assert new['seconds'] is None and 'raw_response' not in new
    assert new['process_interruption']['server_outcome']=='unknown'
    assert new['process_interruption']['native_returncode'] is None
    assert new['process_interruption']['elapsed_until_observation_seconds']==60
    assert has_unknown_interruption_duration(new)


@pytest.mark.parametrize('change',[{'status':'response'},{'transport_attempts':2},{'content_retries':1},
    {'raw_response':{}},{'seconds':0},{'started_utc':'2026-10-15T23:00:00+00:00'}])
def test_only_unresolved_single_attempt_is_closed(change):
    with pytest.raises(ValueError):close({**original(),**change})


def proof():
    return dict(schema='local_judge_root_interruption_observation_v1',native_returncode=None,
        root_tool_session=85414,tool_handle_status='missing',os_matching_processes=[],
        exclusive_scoring_lock_acquired=True,activation_sha256='c'*64,
        endpoint_response_or_native_exit_not_observed=True,failed_requests_reissued=0,
        interrupted_attempts=[{'relative_path':'a/00.json'}])


@pytest.mark.parametrize('change',[{'native_returncode':1},{'tool_handle_status':'running'},
    {'os_matching_processes':[123]},{'exclusive_scoring_lock_acquired':False},
    {'failed_requests_reissued':1},{'activation_sha256':'wrong'},{'interrupted_attempts':[]}])
def test_inadequate_interruption_evidence_is_rejected(change):
    with pytest.raises(ValueError):validate_interruption_observation({**proof(),**change},'c'*64)


def test_lost_handle_and_absent_process_are_not_native_exit():
    assert validate_interruption_observation(proof(),'c'*64)==[{'relative_path':'a/00.json'}]


def test_interrupted_cost_has_unknown_duration_and_usage(tmp_path):
    p=tmp_path/'formal_scores_local_004/requests/00.json';p.parent.mkdir(parents=True)
    record=close();p.write_text(json.dumps(record),encoding='utf-8')
    costs=physical_local_cost([p]);assert costs['duration_unknown_attempts']==1
    assert costs['usage_unknown_attempts']==1 and costs['sum_physical_request_seconds']==0
    row=event_rows(p,tmp_path);event=row['events'][0][1]
    totals=empty_totals();add_event(totals,'Qwen3-14B',event)
    assert totals['duration_unknown_attempts']==1 and totals['usage_unknown_attempts']==1
    assert totals['unresolved_attempt_starts']==0 and totals['sum_known_physical_request_seconds']==0


def test_missing_duration_without_bound_interruption_is_rejected(tmp_path):
    r=close();del r['process_interruption']['observation_sha256']
    p=tmp_path/'formal_scores_local_004/requests/00.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps(r),encoding='utf-8')
    with pytest.raises(ValueError):physical_local_cost([p])
    with pytest.raises(ValueError):event_rows(p,tmp_path)






