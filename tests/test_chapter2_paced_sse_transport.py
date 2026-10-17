from io import BytesIO
import http.client
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import chapter2_paced_sse_transport as paced
from chapter2_sse_record_transport import wire


def test_exact_upload_bytes_and_pacing_without_connecting(monkeypatch):
    writes=[];sleeps=[]
    monkeypatch.setattr(http.client.HTTPSConnection,'send',lambda self,data:writes.append(bytes(data)))
    monkeypatch.setattr(paced.time,'sleep',sleeps.append)
    payload=bytes(range(256))*3+b'last'
    connection=paced.PacedTLSConnection('example.invalid')
    connection.send(payload)
    assert b''.join(writes)==payload and max(map(len,writes))==128
    assert sleeps==[.002]*len(writes)


def test_invalid_upload_never_enters_network(monkeypatch):
    monkeypatch.setattr(http.client.HTTPSConnection,'send',lambda *args:pytest.fail('Network send'))
    with pytest.raises(TypeError):paced.PacedTLSConnection('example.invalid').send('text')


@pytest.mark.parametrize('failure',[None,'disconnect','wrong_model'])
def test_exact_sse_body_one_attempt_and_accurate_metadata(tmp_path,failure):
    class Frozen:
        provider='qwen_proxy'
        def __init__(self):
            self.deployment=SimpleNamespace(model='qwen3-8b',endpoint='https://example.invalid/v1/chat/completions',key='secret-key')
            self.folder=tmp_path;self.timeout=10
    router=SimpleNamespace(RecordedProxyQwenClient=Frozen)
    paced.install(router,'a'*64);client=router.RecordedProxyQwenClient();calls=[]
    class Response(BytesIO):status=200
    def open_(request,**kwargs):
        calls.append(request.data)
        if failure=='disconnect':raise http.client.RemoteDisconnected('closed')
        value=dict(id='unit',created=1,model='other' if failure=='wrong_model' else 'qwen3-8b',
                   choices=[dict(index=0,delta=dict(content='{"answer":"原文"}'),finish_reason='stop')])
        return Response(b'data: '+wire(value)+b'\n\ndata: [DONE]\n\n')
    client.opener=SimpleNamespace(open=open_)
    logical=dict(model='qwen3-8b',stream=False,messages=[dict(role='user',content='原问题')],max_tokens=4096)
    row=client(logical,0)
    assert calls==[wire({**logical,'stream':True,'stream_options':{'include_usage':True}})]
    assert row['logical_request']==logical and row['transport_policy']==paced.POLICY
    assert row['tls_application_write_limit_bytes']==128 and row['tls_inter_write_pause_seconds']==.002
    assert row['certificate_verification'] is True and row['tls_version']=='TLSv1.2'
    assert row['status']==({None:'response','disconnect':'transport_error','wrong_model':'model_mismatch'}[failure])
    assert json.loads((tmp_path/'00.json').read_text(encoding='utf-8'))==row
    assert 'secret-key' not in (tmp_path/'00.json').read_text(encoding='utf-8')
    with pytest.raises(FileExistsError):client(logical,0)
    assert len(calls)==1


def test_adapter_cannot_be_installed_twice():
    router=SimpleNamespace(RecordedProxyQwenClient=type('Frozen',(),{}))
    paced.install(router,'b'*64)
    with pytest.raises(ValueError):paced.install(router,'b'*64)
