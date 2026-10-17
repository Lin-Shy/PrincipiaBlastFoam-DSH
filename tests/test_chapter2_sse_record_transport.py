import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_sse_record_transport import collect, install, InvalidStream, ModelMismatch, wire

def chunk(delta=None, finish=None, model='qwen3-8b', usage=None):
    return dict(id='chat-test',created=123,model=model,
        choices=[] if usage else [dict(index=0,delta=delta or {},finish_reason=finish)],usage=usage)

def events(values,done=True):
    return b''.join(b'data: '+wire(v)+b'\r\n\r\n' for v in values)+(b'data: [DONE]\r\n\r\n' if done else b'')

def test_preserves_unicode_exactly_and_uses_final_usage():
    data=events([chunk({'role':'assistant','content':'{"答'}),chunk({'content':'案":"原文"}'},'stop'),chunk(usage={'prompt_tokens':30,'completion_tokens':10,'total_tokens':40})])
    sink=BytesIO();timing={}
    value=collect(BytesIO(data),'qwen3-8b',sink,timing,time.monotonic())
    assert value['choices'][0]['message']['content']=='{"答案":"原文"}'
    assert value['usage']['total_tokens']==40
    assert sink.getvalue()==data and timing['sse_done']

@pytest.mark.parametrize('values,done,error',[
    ([chunk({'content':'unfinished'})],False,InvalidStream),
    ([chunk({'content':'unfinished'})],True,InvalidStream),
    ([chunk({'content':'wrong'},'stop',model='qwen3-14b')],True,ModelMismatch),
    ([chunk({'content':'one'},'stop'),chunk({'content':'two'})],True,InvalidStream),
    ([chunk({'tool_calls':[{}]},'tool_calls')],True,InvalidStream)])
def test_incomplete_or_identity_changing_streams_never_become_valid(values,done,error):
    with pytest.raises(error):collect(BytesIO(events(values,done)),'qwen3-8b',BytesIO(),{},time.monotonic())

def test_length_finish_and_missing_usage_remain_explicit():
    timing={};value=collect(BytesIO(events([chunk({'content':'partial'},'length')])),'qwen3-8b',BytesIO(),timing,time.monotonic())
    assert value['choices'][0]['finish_reason']=='length'
    assert 'usage' not in value and timing['usage_reported'] is False

def test_client_records_actual_wire_and_logical_identity_without_retries(tmp_path):
    class Frozen:
        provider='qwen_proxy'
        def __init__(self):
            self.deployment=SimpleNamespace(model='qwen3-8b',endpoint='https://example.invalid/v1/chat/completions',key='private')
            self.folder=tmp_path;self.timeout=10
    router=SimpleNamespace(RecordedProxyQwenClient=Frozen);install(router,'a'*64)
    client=router.RecordedProxyQwenClient();calls=[]
    class Response(BytesIO):status=200
    def open_(request,**kwargs):
        calls.append(json.loads(request.data));return Response(events([chunk({'content':'{"ok":true}'},'stop')]))
    client.opener=SimpleNamespace(open=open_)
    logical=dict(model='qwen3-8b',messages=[dict(role='user',content='原文')],temperature=0,max_tokens=4096,stream=False)
    r=client(logical,0)
    assert logical['stream'] is False and 'stream_options' not in logical
    assert calls==[r['request']] and calls[0]['stream'] is True
    assert {k:v for k,v in calls[0].items() if k not in {'stream','stream_options'}}=={k:v for k,v in logical.items() if k!='stream'}
    assert r['status']=='response' and r['logical_request']==logical
    assert r['request_sha256']==hashlib.sha256(wire(calls[0])).hexdigest()
    assert r['raw_response_sha256']==hashlib.sha256((tmp_path/'00.sse').read_bytes()).hexdigest()
    assert 'private' not in (tmp_path/'00.json').read_text(encoding='utf-8')
    with pytest.raises(FileExistsError):client(logical,0)
    assert len(calls)==1

def test_adapter_failure_retains_raw_partial_and_never_retries(tmp_path):
    class Frozen:
        provider='qwen_proxy'
        def __init__(self):
            self.deployment=SimpleNamespace(model='qwen3-8b',endpoint='https://example.invalid/v1/chat/completions',key='private')
            self.folder=tmp_path;self.timeout=10
    router=SimpleNamespace(RecordedProxyQwenClient=Frozen);install(router,'b'*64)
    client=router.RecordedProxyQwenClient();calls=[]
    class Response(BytesIO):status=200
    def open_(request,**kwargs):
        calls.append(request);return Response(events([chunk({'content':'incomplete'})],done=False))
    client.opener=SimpleNamespace(open=open_)
    r=client(dict(model='qwen3-8b',stream=False),0)
    assert r['status']=='invalid_response' and len(calls)==1
    assert (tmp_path/'00.sse').read_bytes() and 'response' not in r
