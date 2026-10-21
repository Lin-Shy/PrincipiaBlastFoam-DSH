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


@pytest.mark.parametrize('workload',[None,'small','bulk'])
def test_14b_routes_to_proxy_for_any_task_size(tmp_path,workload):
    client=routed_client('qwen3-14b',tmp_path/'requests',workload=workload,settings_path=config(tmp_path))
    assert isinstance(client,RecordedProxyQwenClient)
    assert client.deployment.endpoint=='https://example.com/v1/chat/completions'
    assert 'test-secret' not in repr(client.deployment)


@pytest.mark.parametrize('workload',[None,'small','bulk'])
def test_8b_routes_to_local_for_any_task_size(tmp_path,workload):
    path=tmp_path/'local.env'
    path.write_text('QWEN_LOCAL_API_KEY=local-secret\nQWEN_LOCAL_8B_BASE_URL=http://127.0.0.1:8001/v1\nQWEN_LOCAL_8B_MODEL=Qwen3-8B\n',encoding='utf-8')
    client=routed_client('qwen3-8b',tmp_path/'requests',workload=workload,settings_path=path)
    assert isinstance(client,LocalQwenClient)
    assert client.deployment.model=='Qwen3-8B'
    assert client.deployment.max_concurrency==8


@pytest.mark.parametrize('model',['qwen3-32b','auto',''])
def test_unknown_models_rejected_before_config_or_network(tmp_path,model):
    with pytest.raises(ValueError,match='Supported models'):
        routed_client(model,tmp_path/'requests',settings_path=tmp_path/'absent')
    assert not (tmp_path/'requests').exists()


def test_missing_bulk_config_never_falls_back_to_local(tmp_path):
    with pytest.raises(FileNotFoundError):
        routed_client('qwen3-14b',tmp_path,workload='bulk',settings_path=tmp_path/'absent')


def test_model_alone_selects_deployment(tmp_path):
    assert isinstance(routed_client('qwen3-14b',tmp_path,settings_path=config(tmp_path)),RecordedProxyQwenClient)


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


