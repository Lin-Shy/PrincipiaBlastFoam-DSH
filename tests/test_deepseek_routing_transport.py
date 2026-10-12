import importlib.util
import io
import json
from pathlib import Path
import sys
from urllib.error import HTTPError

SCRIPTS = Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('deepseek_transport_test', SCRIPTS / 'run_deepseek_routing.py')
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def test_official_transport_preserves_messages_and_frozen_budget():
    messages = [{'role': 'user', 'content': 'question and catalog'}]
    body = t.request_body(messages, {'temperature': 0, 'max_tokens': 1500})
    assert body['messages'] == messages
    assert body['max_tokens'] == 1500 and body['temperature'] == 0
    assert body['thinking'] == {'type': 'disabled'}
    assert 'response_format' not in body
    assert t.ENDPOINT == 'https://api.deepseek.com/chat/completions'


def test_usage_and_response_are_retained_without_auth_header(monkeypatch):
    def fake_open(request, timeout):
        assert request.get_header('Authorization') == 'Bearer test-only-key'
        assert timeout == 60
        return io.BytesIO(json.dumps({'model': 'versioned-model', 'choices': [
            {'message': {'content': '{"action":"uncovered","request":null}'}, 'finish_reason': 'stop'}
        ], 'usage': {'total_tokens': 20}}).encode())
    monkeypatch.setattr(t, 'urlopen', fake_open)
    result = t.invoke('test-only-key', [], {'temperature': 0, 'max_tokens': 1500, 'timeout_seconds': 60})
    assert result['status'] == 'ok' and result['returned_model'] == 'versioned-model'
    assert result['usage']['total_tokens'] == 20
    assert 'test-only-key' not in json.dumps(result)


def test_http_error_body_is_not_logged(monkeypatch):
    def fake_open(*args, **kwargs):
        raise HTTPError(t.ENDPOINT, 401, 'secret diagnostic', {}, io.BytesIO(b'secret'))
    monkeypatch.setattr(t, 'urlopen', fake_open)
    result = t.invoke('test-only-key', [], {'temperature': 0, 'max_tokens': 1500, 'timeout_seconds': 60})
    assert result == {'status': 'transport_error', 'error_type': 'HTTPError', 'http_status': 401}
