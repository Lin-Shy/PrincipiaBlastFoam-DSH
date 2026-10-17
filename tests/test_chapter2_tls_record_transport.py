import hashlib
import http.client
import json
from pathlib import Path
import ssl
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_tls_record_transport import SplitTLSConnection, install, POLICY, WRITE_BYTES


@pytest.mark.parametrize('size', [1, 511, 512, 513, 4096, 32000])
def test_actual_connection_writes_preserve_bytes_and_bound_tls_records(monkeypatch, size):
    sent = []
    monkeypatch.setattr(http.client.HTTPSConnection, 'send', lambda self, data: sent.append(bytes(data)))
    data = ('证据与默认值'.encode() * (size // 18 + 1))[:size]
    SplitTLSConnection('example.invalid').send(data)
    assert b''.join(sent) == data
    assert all(0 < len(piece) <= WRITE_BYTES for piece in sent)


def test_adapter_preserves_one_attempt_body_identity_and_records_revision(tmp_path):
    calls = []

    class FrozenClient:
        def __init__(self, folder):self.folder = folder
        def __call__(self, body, turn):
            calls.append((body, turn))
            return dict(request=body, status='transport_error', error_type='RemoteDisconnected',
                        request_sha256=hashlib.sha256(json.dumps(body).encode()).hexdigest(),
                        transport_attempts=1, content_retries=0)

    router = SimpleNamespace(RecordedProxyQwenClient=FrozenClient)
    install(router, 'a' * 64)
    client = router.RecordedProxyQwenClient(tmp_path)
    body = dict(model='qwen3-8b', messages=[dict(role='user', content='实际原文')], max_tokens=4096)
    record = client(body, 0)
    assert calls == [(body, 0)]
    assert calls[0][0] is body
    assert record['status'] == 'transport_error'
    assert record['transport_attempts'] == 1
    assert record['transport_policy'] == POLICY
    assert json.loads((tmp_path/'00.json').read_text(encoding='utf-8')) == record
    handler = next(h for h in client.opener.handlers if hasattr(h, '_context'))
    assert handler._context.minimum_version == handler._context.maximum_version == ssl.TLSVersion.TLSv1_2
    assert handler._context.verify_mode == ssl.CERT_REQUIRED
    with pytest.raises(ValueError):install(router, 'b' * 64)


def test_unregistered_adapter_fails_closed():
    with pytest.raises(ValueError):install(SimpleNamespace(), 'not-a-sha256')
