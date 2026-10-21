import importlib.util
import json
from pathlib import Path
import sys
import ssl
from urllib.error import HTTPError
import pytest

MODULES=Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
sys.path.insert(0,str(MODULES))
spec=importlib.util.spec_from_file_location('autonomous_transport',MODULES/'chapter2_autonomous_qa.py')
qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)

class Response:
    def __init__(self,raw):self.raw=raw
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return self.raw

def test_transport_retry_preserves_identical_request_and_no_secret(tmp_path,monkeypatch):
    bodies=[]
    def open_request(request,timeout,context):
        assert context.minimum_version==context.maximum_version==ssl.TLSVersion.TLSv1_2
        assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
        bodies.append(request.data)
        if len(bodies)<3:raise HTTPError('https://test.invalid',503,'unavailable',None,None)
        return Response(b'{"model":"qwen3-8b","choices":[],"usage":{"completion_tokens":1}}')
    monkeypatch.setattr(qa,'urlopen',open_request);monkeypatch.setattr(qa.time,'sleep',lambda x:None)
    client=qa.RecordedQwenClient('https://test.invalid','private_test_credential',tmp_path)
    result=client({'model':'qwen3-8b','messages':[]},0)
    assert result['status']=='response' and len(bodies)==3 and len(set(bodies))==1
    assert 'private_test_credential' not in (tmp_path/'00.json').read_text(encoding='utf-8')

def test_invalid_response_is_preserved_without_content_retry(tmp_path,monkeypatch):
    requests=[]
    def open_request(request,timeout,context):requests.append(request.data);return Response(b'[1,2]')
    monkeypatch.setattr(qa,'urlopen',open_request)
    client=qa.RecordedQwenClient('https://test.invalid','private',tmp_path)
    body={'model':'qwen3-8b','messages':[]}
    assert client(body,0)['status']=='invalid_response'
    assert client(body,0)['status']=='invalid_response' and len(requests)==1
    with pytest.raises(ValueError,match='drift'):client({**body,'max_tokens':30},0)

def test_unresolved_inflight_is_not_silently_resampled(tmp_path):
    body={'model':'qwen3-8b'};fingerprint=qa.hashlib.sha256(qa.wire(body).encode('utf-8')).hexdigest()
    qa.save(tmp_path/'00.json',{'request_sha256':fingerprint,'status':'in_flight','events':[]})
    with pytest.raises(RuntimeError,match='in-flight'):qa.RecordedQwenClient('https://test.invalid','private',tmp_path)(body,0)

def test_exhausted_transport_stays_failed_without_a_fourth_attempt(tmp_path,monkeypatch):
    body={'model':'qwen3-8b'};fingerprint=qa.hashlib.sha256(qa.wire(body).encode('utf-8')).hexdigest()
    qa.save(tmp_path/'00.json',{'request_sha256':fingerprint,'status':'transport_error','events':[{}, {}, {}]})
    monkeypatch.setattr(qa,'urlopen',lambda *a,**k:pytest.fail('unregistered fourth transport attempt'))
    assert qa.RecordedQwenClient('https://test.invalid','private',tmp_path)(body,0)['status']=='transport_error'

def test_direct_transport_preserves_certificate_checks_and_disables_only_os_proxy(monkeypatch):
    seen=[]
    class Opener:
        def open(self,request,timeout):return 'opened'
    def build(*handlers):seen.extend(handlers);return Opener()
    monkeypatch.setattr(qa,'build_opener',build);context=ssl.create_default_context()
    assert qa.urlopen('request',10,context)=='opened'
    assert seen[0].proxies=={} and seen[1]._context is context
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
