"""Verify current service limits and shared admission without network calls."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from threading import Event, Lock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
import chapter2_qwen_limits as limits
from chapter2_qwen_local import load_model
from chapter2_qwen_proxy_config import load_settings, settings
from chapter2_qwen_routing import routed_client


def config(tmp_path, provider, maximum):
    path = tmp_path / (provider + '.env')
    text = ('QWEN_LOCAL_API_KEY=test-secret\n'
            'QWEN_LOCAL_8B_BASE_URL=http://127.0.0.1:8001/v1\nQWEN_LOCAL_8B_MODEL=Qwen3-8B\n'
            if provider == 'local' else
            'QWEN_PROXY_API_KEY=test-secret\nQWEN_PROXY_BASE_URL=https://example.com/v1\n')
    path.write_text(text + f'QWEN_{provider.upper()}_MAX_CONCURRENCY={maximum}\n', encoding='utf-8')
    return path


def test_defaults_and_legacy_two_value_proxy_interface(tmp_path):
    path = tmp_path / 'proxy.env'
    path.write_text('QWEN_PROXY_API_KEY=test-secret\nQWEN_PROXY_BASE_URL=https://example.com/v1\n')
    assert load_settings(path)[2] == 20
    assert settings(path) == ('https://example.com/v1', 'test-secret')
    assert load_model('qwen3-8b', config(tmp_path, 'local', 8)).max_concurrency == 8


@pytest.mark.parametrize('provider,invalid', [('local', '9'), ('proxy', '21'),
    ('local', '0'), ('proxy', '-1'), ('local', '1.5'), ('proxy', 'true'), ('proxy', '')])
def test_invalid_concurrency_fails_before_network(tmp_path, provider, invalid):
    path = config(tmp_path, provider, invalid)
    with pytest.raises(ValueError, match='CONCURRENCY'):
        load_model('qwen3-8b', path) if provider == 'local' else load_settings(path)


@pytest.mark.parametrize('provider,model,workload',
    [('local', 'qwen3-8b', 'small'), ('proxy', 'qwen3-14b', 'bulk')])
def test_multiple_clients_share_inflight_limit(tmp_path, monkeypatch, provider, model, workload):
    monkeypatch.setattr(limits, '_limits', {})
    path = config(tmp_path, provider, 2)
    clients = [routed_client(model, tmp_path / str(i), workload=workload, settings_path=path) for i in range(6)]
    assert all(c.limiter is clients[0].limiter for c in clients)
    lock, full = Lock(), Event()
    active = peak = 0

    class Response:
        status = 200
        def __enter__(self):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active >= 2:
                    full.set()
            return self
        def read(self):
            assert full.wait(3), 'two requests should be admitted concurrently'
            return json.dumps(dict(model=clients[0].deployment.model,
                choices=[dict(message=dict(content='hello'))])).encode()
        def __exit__(self, *args):
            nonlocal active
            with lock:
                active -= 1

    class Opener:
        def open(self, request, timeout): return Response()

    for client in clients:
        client.opener = Opener()
    body = dict(model=model, messages=[dict(role='user', content='hello')])
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda client: client(body, 0), clients))
    assert peak == 2 and active == 0
    assert all(r['status'] == 'response' and r['max_concurrency'] == 2 for r in results)
    # Error paths must also release the shared slot.
    class BrokenOpener:
        def open(self, request, timeout): raise TimeoutError()
    clients[0].opener = BrokenOpener()
    assert clients[0](body, 1)['status'] == 'transport_error'
    assert clients[0].limiter.acquire(blocking=False)
    assert clients[0].limiter.acquire(blocking=False)
    assert not clients[0].limiter.acquire(blocking=False)
    clients[0].limiter.release()
    clients[0].limiter.release()


def test_conflicting_endpoint_config_cannot_create_a_second_budget(monkeypatch):
    monkeypatch.setattr(limits, '_limits', {})
    limits.endpoint_limiter('https://example.com/v1/chat/completions', 20)
    with pytest.raises(ValueError, match='Conflicting'):
        limits.endpoint_limiter('https://example.com/v1/chat/completions', 10)
