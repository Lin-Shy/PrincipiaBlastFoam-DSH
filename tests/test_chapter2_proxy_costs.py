from pathlib import Path
import hashlib,json,sys
import pytest

SOURCE=Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
sys.path.insert(0,str(SOURCE))
from chapter2_proxy_costs import physical_proxy_cost
from chapter2_knowledge_stage_costs import reconcile


def write(root,relative,*,native=False,status='response',usage=None,seconds=2,started='2026-10-16T04:00:01+00:00'):
    body=dict(model='qwen3-14b',messages=[])
    request_hash=hashlib.sha256(json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    r=dict(request=body,request_sha256=request_hash,endpoint='https://example.com/v1/chat/completions',status=status)
    usage=usage if usage is not None else dict(prompt_tokens=10,completion_tokens=5)
    if native:
        r.update(provider='qwen_proxy',model='qwen3-14b',transport_attempts=1,
            started_utc=started,seconds=seconds,raw_response=dict(usage=usage))
    else:
        r['events']=[dict(attempt=1,started_unix=1792123200.,status=status)]
        if status!='in_flight':r['events'][0].update(seconds=seconds,usage=usage)
    p=root/relative;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(r),encoding='utf-8');return p


def test_old_and_native_proxy_events_reconcile_with_no_double_charge(tmp_path):
    a=write(tmp_path,'formal_scores/c/sessions/q/requests/00.json')
    b=write(tmp_path,'formal_scores/c/sessions/q/requests/01.json',native=True)
    c=tmp_path/'formal_scores/c/sessions/q/requests/02.json';c.write_bytes(a.read_bytes())
    cost=physical_proxy_cost([a,b,c,a],tmp_path)
    assert cost['physical_attempts']==2 and cost['known_total_tokens']==30
    assert cost['sum_physical_request_seconds']==4 and cost['duplicate_physical_events_not_recharged']==1


def test_unresolved_requires_exact_seal_and_never_gets_imputed_cost(tmp_path):
    p=write(tmp_path,'formal_scores/c/sessions/q/requests/00.json',status='in_flight')
    with pytest.raises(ValueError,match='Unsealed'):physical_proxy_cost([p],tmp_path)
    with pytest.raises(ValueError,match='Unsealed'):physical_proxy_cost([p],tmp_path,{p.relative_to(tmp_path).as_posix():'wrong'})
    sealed={p.relative_to(tmp_path).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()}
    cost=physical_proxy_cost([p],tmp_path,sealed)
    assert cost['physical_attempts']==cost['usage_unknown_attempts']==cost['duration_unknown_attempts']==1
    assert cost['known_total_tokens']==0 and cost['money_cost'] is None
    assert cost['sealed_interrupted_unknown_attempts']==1


def test_proxy_probe_is_counted_but_metadata_and_opinions_are_never_parsed(tmp_path):
    write(tmp_path,'audit/proxy_bulk_transition_001/connectivity-14b/00.json',native=True,started='2026-10-16T04:00:00+00:00')
    write(tmp_path,'formal_scores/c/sessions/q/requests/00.json',native=True)
    for relative in ['formal_scores/c/sessions/q/score.json','formal_analysis/report.json',
            'formal_original_review/pack/verdicts.json','audit/proxy_bulk_transition_001/progress.json']:
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('not JSON')
    report=reconcile(tmp_path)
    assert report['grand_total']['physical_attempts']==2
    assert report['stages']['connectivity_diagnostics']['physical_attempts']==1
    assert report['stages']['formal_primary_grading']['physical_attempts']==1


@pytest.mark.parametrize('bad_seconds',[None,-1,True,float('inf')])
def test_terminal_duration_must_be_known_except_registered_interruption(tmp_path,bad_seconds):
    p=write(tmp_path,'formal_scores/c/sessions/q/requests/00.json',native=True,seconds=bad_seconds)
    with pytest.raises(ValueError,match='duration'):physical_proxy_cost([p],tmp_path)


def test_failed_native_proxy_preserves_unknown_usage(tmp_path):
    p=write(tmp_path,'formal_scores/c/sessions/q/requests/00.json',native=True,status='http_rejected',usage={})
    cost=physical_proxy_cost([p],tmp_path)
    assert cost['physical_attempts']==1 and cost['usage_unknown_attempts']==1
    assert cost['known_total_tokens']==0 and cost['duration_unknown_attempts']==0
