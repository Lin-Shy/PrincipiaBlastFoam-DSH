"""Offline checks: registering a transport must not silently select another."""
from pathlib import Path
import sys
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
import json
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import chapter2_sse_scoring as scoring
import chapter2_sse_record_transport as sse
import chapter2_paced_sse_transport as paced


@pytest.mark.parametrize('policy',[None,paced.POLICY])
def test_exact_registered_installer(monkeypatch,policy):
    calls=[];router=SimpleNamespace();digest='a'*64
    monkeypatch.setattr(sse,'install',lambda *args:calls.append(('sse',args)))
    monkeypatch.setattr(paced,'install',lambda *args:calls.append(('paced',args)))
    amendment={} if policy is None else dict(paced_transport_policy=policy)
    scoring.install_transport(router,amendment,digest)
    assert calls==[('sse' if policy is None else 'paced',(router,digest))]


def test_unknown_policy_rejected_before_installation(monkeypatch):
    def forbidden(*args):pytest.fail('Unregistered transport installed')
    monkeypatch.setattr(sse,'install',forbidden)
    monkeypatch.setattr(paced,'install',forbidden)
    with pytest.raises(ValueError,match='Unexpected paced grading transport'):
        scoring.install_transport(SimpleNamespace(),dict(paced_transport_policy='unknown'),'b'*64)


@pytest.fixture
def load_probe(tmp_path):
    now=datetime(2026,10,17,tzinfo=timezone.utc);digest='c'*64;rows=[]
    for model in ('qwen3-8b','qwen3-14b'):
        for index in range(16):
            folder=tmp_path/model/str(index)/'requests';folder.mkdir(parents=True)
            raw=folder/'00.sse';raw.write_bytes(b'data: [DONE]\n\n')
            logical=dict(model=model,messages=[dict(role='user',content='synthetic transport check')])
            record=dict(status='response',model=model,response=dict(model=model),transport_revision_sha256=digest,
                        raw_sse_file=raw.name,raw_response_sha256=scoring.sha(raw),sse_done=True,
                        logical_request=logical,request={**logical,'stream':True,'stream_options':{'include_usage':True}})
            physical=folder/'00.json';physical.write_text(json.dumps(record),encoding='utf-8')
            rows.append(dict(model=model,index=index,status='response',receipt_sha256=scoring.sha(physical)))
    path=tmp_path/'receipt.json'
    value=dict(created_utc=now.isoformat(),transport_amendment_sha256=digest,formal_result=False,
               actual_test_questions_used=False,old_formal_requests_reissued=False,workers_per_model=16,results=rows)
    path.write_text(json.dumps(value),encoding='utf-8')
    return path,digest,now


def test_fresh_load_probe_reads_all_physical_receipts(load_probe):
    path,digest,now=load_probe
    assert len(scoring.validate_load_probe(path,digest,now=now)['results'])==32


@pytest.mark.parametrize('change',['stale','future','duplicate','summary_identity','physical_identity','raw_stream','wire_transform'])
def test_load_probe_rejects_stale_or_changed_physical_evidence(load_probe,change):
    path,digest,now=load_probe
    value=json.loads(path.read_text());physical=path.parent/'qwen3-14b/15/requests/00.json'
    if change=='stale':now+=timedelta(seconds=601)
    elif change=='future':now-=timedelta(seconds=1)
    elif change=='duplicate':value['results'][-1]=dict(value['results'][-2])
    elif change=='summary_identity':value['results'][-1]['model']='qwen3-8b'
    elif change=='raw_stream':(physical.parent/'00.sse').write_bytes(b'truncated')
    else:
        record=json.loads(physical.read_text())
        if change=='physical_identity':record['response']['model']='different-model'
        else:record['request']['messages']=[dict(role='user',content='changed wire body')]
        physical.write_text(json.dumps(record),encoding='utf-8')
        # Even a re-signed summary must not admit a changed response identity or body.
        value['results'][-1]['receipt_sha256']=scoring.sha(physical)
    path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError):scoring.validate_load_probe(path,digest,now=now)
