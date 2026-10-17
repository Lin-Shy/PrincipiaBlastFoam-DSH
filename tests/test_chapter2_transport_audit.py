import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_sse_record_transport import collect,wire
from chapter2_transport_audit import verify_request,audit

def receipt(tmp_path):
    folder=tmp_path/'sessions/test/requests';folder.mkdir(parents=True);path=folder/'00.json'
    logical=dict(model='qwen3-8b',messages=[dict(role='user',content='synthetic')],stream=False,max_tokens=4096)
    actual={**logical,'stream':True,'stream_options':{'include_usage':True}}
    chunk=dict(id='x',created=1,model='qwen3-8b',choices=[dict(index=0,delta=dict(content='exact'),finish_reason='stop')])
    raw=b'data: '+wire(chunk)+b'\n\ndata: [DONE]\n\n';(folder/'00.sse').write_bytes(raw)
    payload=collect(BytesIO(raw),'qwen3-8b',BytesIO(),{},0);sha=lambda b:hashlib.sha256(b).hexdigest()
    row=dict(provider='qwen_proxy',model='qwen3-8b',transport_attempts=1,content_retries=0,
        request=actual,request_sha256=sha(wire(actual)),logical_request=logical,logical_request_sha256=sha(wire(logical)),
        raw_sse_file='00.sse',raw_response_sha256=sha(raw),raw_response=payload,response=payload,
        canonical_response_sha256=sha(wire(payload)),status='response',sse_done=True,
        transport_policy='synthetic_test',started_utc='2026-10-17T00:00:00+00:00',seconds=2.0)
    path.write_text(json.dumps(row),encoding='utf-8');return path,row

def test_raw_replay_and_unknown_usage_are_preserved(tmp_path):
    path,row=receipt(tmp_path);verify_request(path,row);value=audit(tmp_path)
    assert value['terminal_requests']==1 and value['cohorts'][0]['usage_unknown_attempts']==1
    assert value['cohorts'][0]['money_cost'] is None

@pytest.mark.parametrize('change',['wire','logical','raw','canonical'])
def test_tampered_wire_logical_raw_or_canonical_bytes_fail(tmp_path,change):
    path,row=receipt(tmp_path)
    if change=='wire':row['request']['max_tokens']=10
    elif change=='logical':row['logical_request']['max_tokens']=10
    elif change=='raw':(path.parent/'00.sse').write_bytes(b'changed')
    else:
        row['raw_response']=copy.deepcopy(row['raw_response']);row['raw_response']['choices'][0]['message']['content']='repaired'
    with pytest.raises(ValueError):verify_request(path,row)

def test_live_request_is_never_counted_as_closed(tmp_path):
    path,row=receipt(tmp_path);row['status']='in_flight';path.write_text(json.dumps(row),encoding='utf-8')
    with pytest.raises(ValueError):audit(tmp_path)
    snapshot=audit(tmp_path,True)
    assert snapshot['terminal_requests']==0 and len(snapshot['in_flight_requests_excluded'])==1

def test_failed_stream_with_invalid_payload_still_has_unknown_cost(tmp_path):
    path,row=receipt(tmp_path);row.update(status='invalid_response',raw_response=None)
    path.write_text(json.dumps(row),encoding='utf-8')
    value=audit(tmp_path)
    assert value['cohorts'][0]['statuses']=={'invalid_response':1}
    assert value['cohorts'][0]['usage_unknown_attempts']==1

def test_admission_wait_is_separate_from_physical_latency(tmp_path):
    path,row=receipt(tmp_path)
    row.update(request_admission_wait_seconds=3.5)
    path.write_text(json.dumps(row),encoding='utf-8')
    cohort=audit(tmp_path)['cohorts'][0]
    assert cohort['sum_physical_seconds']==2.0
    assert cohort['sum_known_admission_wait_seconds']==3.5
    assert cohort['admission_wait_known_attempts']==1
    assert cohort['admission_wait_unknown_attempts']==0

def test_unrecorded_legacy_admission_wait_is_unknown(tmp_path):
    receipt(tmp_path);cohort=audit(tmp_path)['cohorts'][0]
    assert cohort['admission_wait_known_attempts']==0
    assert cohort['admission_wait_unknown_attempts']==1
    assert cohort['sum_known_admission_wait_seconds'] is None

@pytest.mark.parametrize('wait',[-1,float('nan'),float('inf'),True,'3.5'])
def test_invalid_admission_wait_is_rejected(tmp_path,wait):
    path,row=receipt(tmp_path);row['request_admission_wait_seconds']=wait
    path.write_text(json.dumps(row),encoding='utf-8')
    with pytest.raises(ValueError,match='admission waiting'):
        audit(tmp_path)
