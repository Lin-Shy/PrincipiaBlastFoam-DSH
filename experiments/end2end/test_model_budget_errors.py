"""Exercise the real loopback HTTP boundary without a model provider."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import http.client
import json
import threading
import urllib.error
import urllib.request
import pytest
from model_budget import Gate
from model_budget_errors import serve

RAW = b'data: {"usage":{"prompt_tokens":8,"completion_tokens":2,"total_tokens":10}}\n\ndata: [DONE]\n\n'


@contextmanager
def running(tmp_path, forward, limit=1):
    gate = Gate(tmp_path / 'gate', 'm', limit, 10, forward)
    server = serve(gate)
    def request(body=None, token=None):
        payload = json.dumps({'model': 'm'} if body is None else body).encode()
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
            data=payload, headers={'Authorization': 'Bearer ' + (token or gate.token)})
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read()
    try:
        yield gate, request
    finally:
        server.shutdown()
        server.server_close()


def test_success_and_local_budget_are_distinct_from_upstream_rate_limit(tmp_path):
    calls = []
    with running(tmp_path, lambda body: calls.append(body) or RAW) as (gate, request):
        assert request({'model': 'm', 'max_tokens': 100}) == (200, RAW)
        status, raw = request()
        assert status == 409 and json.loads(raw)['error']['code'] == 'request_budget_exhausted'
        assert len(calls) == 1 and calls[0]['max_tokens'] == 10
        assert gate.events[0]['state'] == 'settled'


@pytest.mark.parametrize('error,status,code', [
    (http.client.RemoteDisconnected('secret endpoint'), 502, 'request_processing_failed'),
    (TimeoutError('secret'), 504, 'upstream_timeout'),
    (urllib.error.URLError(TimeoutError('secret')), 504, 'upstream_timeout'),
    (urllib.error.URLError('secret'), 502, 'upstream_transport_error'),
    (urllib.error.HTTPError('secret', 429, 'secret', {}, None), 429, 'upstream_http_error'),
    (MemoryError('synthetic; no memory pressure'), 500, 'host_memory_error'),
    (ValueError('request gate closed/exhausted'), 502, 'request_processing_failed'),
])
def test_failure_is_not_refunded_or_retried(tmp_path, error, status, code):
    calls = []
    def forward(body):
        calls.append(body)
        raise error
    with running(tmp_path, forward, 3) as (gate, request):
        actual, raw = request()
        assert actual == status and json.loads(raw)['error']['code'] == code
        assert b'secret' not in raw
        assert request()[0] == 409
        assert len(calls) == len(gate.events) == 1
        assert gate.closed and gate.events[0]['state'] == 'unknown'
        assert gate.events[0]['error_type'] == type(error).__name__
        assert json.loads((gate.root / 'ledger.json').read_text())['events'] == gate.events


def test_missing_usage_remains_unknown(tmp_path):
    with running(tmp_path, lambda body: b'data: [DONE]\n\n') as (gate, request):
        assert request()[0] == 502
        assert gate.closed and gate.events[0]['state'] == 'unknown'


@pytest.mark.parametrize('body', [[], {'model': 'other'}, {'model': 'm', 'max_tokens': True}])
def test_bad_input_never_reserves_request(tmp_path, body):
    with running(tmp_path, lambda body: pytest.fail('forwarded invalid input')) as (gate, request):
        assert request(body)[0] == 400
        assert request(token='wrong')[0] == 403
        assert gate.events == []


def test_concurrent_request_does_not_forward_or_reserve_twice(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def forward(body):
        entered.set()
        assert release.wait(5)
        return RAW
    with running(tmp_path, forward) as (gate, request), ThreadPoolExecutor() as pool:
        pending = pool.submit(request)
        try:
            assert entered.wait(5)
            status, raw = request()
            assert status == 409 and json.loads(raw)['error']['code'] == 'request_in_flight'
        finally:
            release.set()
        assert pending.result() == (200, RAW)
        assert len(gate.events) == 1
