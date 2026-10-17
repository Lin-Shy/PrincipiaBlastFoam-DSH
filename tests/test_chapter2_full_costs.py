from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_full_costs import physical_cost
from chapter2_v2_retrieval_probe import save


def receipt(status,start,usage=None):
    return dict(provider='qwen_proxy',transport_attempts=1,content_retries=0,status=status,
        endpoint='https://example.invalid/v1/chat/completions',model='qwen3-8b',request_sha256='a'*64,
        started_utc=start,seconds=2,raw_response=dict(usage=usage) if usage else None)


def test_new_receipts_keep_failures_unknown_usage_and_ignore_repeated_canonical_paths(tmp_path):
    known=receipt('response','2026-10-17T00:00:00+00:00',dict(prompt_tokens=10,completion_tokens=3))
    failed=receipt('transport_error','2026-10-17T00:00:01+00:00')
    for name,value in [('a',known),('b',failed)]:save(tmp_path/(name+'.json'),value)
    cost=physical_cost([tmp_path/'a.json',tmp_path/'b.json',tmp_path/'a.json'])
    assert cost['physical_attempts']==2 and cost['repeated_canonical_paths_not_recharged']==1
    assert cost['known_total_tokens']==13 and cost['usage_unknown_attempts']==1
    assert cost['timestamp_overlap_estimate_peak']=={'qwen3-8b':2}
    assert cost['money_cost'] is None and cost['host_ai_cost'] is None


def test_live_receipt_cannot_be_reported_as_terminal_cost(tmp_path):
    save(tmp_path/'live.json',receipt('in_flight','2026-10-17T00:00:00+00:00'))
    with pytest.raises(ValueError,match='live'):physical_cost(tmp_path.glob('*.json'))


def test_distinct_concurrent_calls_with_same_timestamp_and_body_are_both_charged(tmp_path):
    value=receipt('response','2026-10-17T00:00:00+00:00',dict(prompt_tokens=10,completion_tokens=3))
    save(tmp_path/'left.json',value)
    save(tmp_path/'right.json',{**value,'seconds':2.1})
    cost=physical_cost(tmp_path.glob('*.json'))
    assert cost['physical_attempts']==2 and cost['known_total_tokens']==26
    assert cost['timestamp_identity_collisions_retained']==1
