import json
from pathlib import Path
import sys
from urllib.error import HTTPError

import pytest

SOURCE=Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
sys.path.insert(0,str(SOURCE))
from chapter2_qwen_routing import routed_client, RecordedProxyQwenClient
from chapter2_recorded_requests import recorded_or_new
from chapter2_qwen_local import LocalQwenClient


def config(tmp_path):
    path=tmp_path/'proxy.env'
    path.write_text('QWEN_PROXY_API_KEY=test-secret\nQWEN_PROXY_BASE_URL=https://example.com/v1\n',encoding='utf-8')
    return path


def body():
    return dict(model='qwen3-14b',messages=[dict(role='user',content='unchanged')],enable_thinking=False,max_tokens=4096)


def test_bulk_routes_only_to_explicit_proxy_and_hides_key(tmp_path):
    client=routed_client('qwen3-14b',tmp_path/'requests',workload='bulk',settings_path=config(tmp_path))
    assert isinstance(client,RecordedProxyQwenClient)
    assert client.deployment.endpoint=='https://example.com/v1/chat/completions'
    assert 'test-secret' not in repr(client.deployment)


def test_small_routes_to_configured_local_model(tmp_path):
    path=tmp_path/'local.env'
    path.write_text('QWEN_LOCAL_API_KEY=local-secret\nQWEN_LOCAL_14B_BASE_URL=http://127.0.0.1:8001/v1\nQWEN_LOCAL_14B_MODEL=Qwen3-14B\n',encoding='utf-8')
    client=routed_client('qwen3-14b',tmp_path/'requests',workload='small',settings_path=path)
    assert isinstance(client,LocalQwenClient)
    assert client.deployment.model=='Qwen3-14B'


def test_missing_bulk_config_never_falls_back_to_local(tmp_path):
    with pytest.raises(FileNotFoundError):
        routed_client('qwen3-14b',tmp_path,workload='bulk',settings_path=tmp_path/'absent')


def test_explicit_workload_required(tmp_path):
    with pytest.raises(ValueError):routed_client('qwen3-14b',tmp_path,workload='auto')


@pytest.mark.parametrize('error',[TimeoutError(),HTTPError('https://example.com',502,'bad gateway',{},None)])
def test_one_attempt_failure_preserves_request_and_never_reissues(tmp_path,error):
    client=RecordedProxyQwenClient('qwen3-14b',tmp_path/'requests',config(tmp_path))
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append(request);raise error
    client.opener=Opener(); value=body(); result=client(value,0)
    assert result['status'] in {'transport_error','http_rejected'}
    assert result['request']==value and result['transport_attempts']==1
    assert 'test-secret' not in (tmp_path/'requests/00.json').read_text()
    with pytest.raises(FileExistsError):client(value,0)
    assert len(calls)==1
    assert recorded_or_new(client,value,0)['status']==result['status']
    assert len(calls)==1


def test_existing_inflight_is_never_replayed(tmp_path):
    client=RecordedProxyQwenClient('qwen3-14b',tmp_path/'requests',config(tmp_path))
    client.folder.mkdir()
    (client.folder/'00.json').write_text(json.dumps(dict(status='in_flight',request=body(),endpoint=client.deployment.endpoint)),encoding='utf-8')
    with pytest.raises(ValueError,match='Unresolved'):recorded_or_new(client,body(),0)


def test_success_preserves_exact_body_and_checks_returned_model(tmp_path):
    client=RecordedProxyQwenClient('qwen3-14b',tmp_path/'requests',config(tmp_path))
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps(dict(model='different-model',choices=[dict(message=dict(content='{}'))])).encode()
    class Opener:
        def open(self,request,timeout):return Response()
    client.opener=Opener()
    result=client(body(),0)
    assert result['status']=='model_mismatch' and result['request']==body()
    assert result['raw_response']==result['response']


def test_existing_terminal_request_binding_must_match(tmp_path):
    client=RecordedProxyQwenClient('qwen3-14b',tmp_path/'requests',config(tmp_path))
    client.folder.mkdir()
    (client.folder/'00.json').write_text(json.dumps(dict(status='response',request=body(),endpoint='https://other.example/v1')),encoding='utf-8')
    with pytest.raises(ValueError,match='identity'):recorded_or_new(client,body(),0)


