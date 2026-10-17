from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import chapter2_spaced_sse_transport as spaced
from chapter2_sse_record_transport import wire


def test_spacing_is_shared_by_same_model_but_independent_between_models():
    clock=[0.0];sleeps=[]
    def sleep(seconds):sleeps.append(seconds);clock[0]+=seconds
    gate=spaced.StartSpacing(clock=lambda:clock[0],sleep=sleep)
    assert gate.wait('qwen3-8b')==0
    assert gate.wait('qwen3-14b')==0
    assert gate.wait('qwen3-8b')==.25
    assert gate.wait('qwen3-14b')==0
    clock[0]=2
    assert gate.wait('qwen3-8b')==0
    assert sleeps==[.25]
    with pytest.raises(ValueError):gate.wait('qwen3-other')


def test_sixteen_workers_do_not_bypass_shared_admission_clock():
    clock=[0.0];admissions=[]
    def sleep(seconds):clock[0]+=seconds
    gate=spaced.StartSpacing(clock=lambda:clock[0],sleep=sleep)
    # Capture each admitted value under the same model lock via next_start writes.
    class Starts(dict):
        def __setitem__(self,key,value):admissions.append(value-.25);super().__setitem__(key,value)
    gate.next_start=Starts(gate.next_start)
    with ThreadPoolExecutor(max_workers=16) as pool:list(pool.map(gate.wait,['qwen3-8b']*16))
    assert sorted(admissions)==[i*.25 for i in range(16)]


def test_early_wake_is_not_admitted_before_its_slot():
    clock=[0.0];sleeps=[]
    def sleep(seconds):
        sleeps.append(seconds);clock[0]+=seconds/2 if len(sleeps)==1 else seconds
    gate=spaced.StartSpacing(clock=lambda:clock[0],sleep=sleep)
    gate.wait('qwen3-8b');assert gate.wait('qwen3-8b')==.25
    assert sleeps==[.25,.125]


@pytest.mark.parametrize('failure',[None,'http502','wrong_model'])
def test_exact_body_and_terminal_record_are_preserved_with_spacing(tmp_path,monkeypatch,failure):
    class Frozen:
        provider='qwen_proxy'
        def __init__(self):
            self.deployment=SimpleNamespace(model='qwen3-8b',endpoint='https://example.invalid/v1/chat/completions',key='private')
            self.folder=tmp_path;self.timeout=10
    waits=[]
    monkeypatch.setattr(spaced.StartSpacing,'wait',lambda self,model:waits.append(model) or .75)
    router=SimpleNamespace(RecordedProxyQwenClient=Frozen);spaced.install(router,'d'*64)
    client=router.RecordedProxyQwenClient();calls=[]
    class Response(BytesIO):status=200
    def open_(request,**kwargs):
        calls.append(request.data)
        if failure=='http502':raise HTTPError(request.full_url,502,'upstream',{},None)
        value=dict(id='unit',created=1,model='other' if failure=='wrong_model' else 'qwen3-8b',
                   choices=[dict(index=0,delta=dict(content='{"answer":"unchanged"}'),finish_reason='stop')])
        return Response(b'data: '+wire(value)+b'\n\ndata: [DONE]\n\n')
    client.opener=SimpleNamespace(open=open_)
    logical=dict(model='qwen3-8b',stream=False,messages=[dict(role='user',content='original question')],max_tokens=4096)
    row=client(logical,0)
    assert calls==[wire({**logical,'stream':True,'stream_options':{'include_usage':True}})]
    assert row['logical_request']==logical and row['request_admission_policy']==spaced.POLICY
    assert row['request_admission_wait_seconds']==.75 and row['request_admission_min_interval_seconds']==.25
    assert row['transport_policy']==spaced.POLICY and row['base_paced_policy']==spaced.PACED_POLICY
    assert row['transport_attempts']==1 and row['content_retries']==0
    assert row['tls_application_write_limit_bytes']==128 and row['tls_inter_write_pause_seconds']==.002
    assert row['status']=={None:'response','http502':'http_rejected','wrong_model':'model_mismatch'}[failure]
    assert waits==['qwen3-8b'] and json.loads((tmp_path/'00.json').read_text())==row
    if failure=='http502':assert row['http_status']==502
    with pytest.raises(FileExistsError):client(logical,0)
    assert len(calls)==1


def test_no_second_transport_installation():
    router=SimpleNamespace(RecordedProxyQwenClient=type('Frozen',(),{}));spaced.install(router,'e'*64)
    with pytest.raises(ValueError):spaced.install(router,'e'*64)
