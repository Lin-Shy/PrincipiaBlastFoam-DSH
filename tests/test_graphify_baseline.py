import io
import json
import types
from pathlib import Path

import pytest

from experiments.retrieval_method import graphify_baseline as baseline


def test_redaction_and_read_meter(tmp_path):
    output = tmp_path / "record.json"
    baseline.write_json(output, {"data": "fake-secret"}, "fake-secret")
    assert "fake-secret" not in output.read_text()
    audit = baseline.Audit(tmp_path, "")
    restore = audit.install_reads()
    try:
        output.read_text()
        output.read_bytes()
    finally:
        restore()
    counts = audit.summary()["path_read_counters"]
    assert sum(row["value"] for row in counts if row["unit"] == "calls") == 2
    log, stream = io.StringIO(), io.StringIO()
    baseline.SafeTee(stream, log, "fake-secret").write("credential=fake-secret")
    assert log.getvalue() == stream.getvalue() == "credential=[REDACTED]"


@pytest.mark.parametrize("transport_module", ["httpx", "httpx2"])
def test_http_meter_preserves_response_and_unknown_failure(tmp_path, monkeypatch, transport_module):
    import sys
    class Client:
        calls = 0
        def send(self, request):
            self.calls += 1
            if self.calls == 2:
                raise ConnectionError("simulated")
            return response
    response = types.SimpleNamespace(status_code=200, read=lambda: json.dumps({
        "model": "deepseek-flash",
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        "choices": [{"message": {"content": "fake-secret"}}],
    }).encode())
    request = types.SimpleNamespace(
        method="POST", content=b'{"model":"test","messages":[]}',
        url=types.SimpleNamespace(host="api.deepseek.com", path="/chat/completions"),
    )
    base_client = types.SimpleNamespace(**{transport_module: types.SimpleNamespace(Client=Client)})
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(_base_client=base_client))
    original = Client.send
    audit = baseline.Audit(tmp_path, "fake-secret")
    restore = audit.install_http()
    try:
        client = Client()
        assert client.send(request) is response
        with pytest.raises(ConnectionError):
            client.send(request)
    finally:
        restore()
    assert Client.send is original
    costs = audit.summary()
    assert costs["http_attempts"] == 2
    assert costs["reported_usage_sum"]["total_tokens"] == 16
    assert costs["unknown_usage_attempts"] == 1
    assert costs["reported_usage_is_lower_bound"] is True
    assert "fake-secret" not in (tmp_path / "http/00001.json").read_text()
    assert json.loads((tmp_path / "http/00002.json").read_text())["usage"] is None


def test_frozen_corpus_verification_rejects_content_and_scope_changes(tmp_path):
    root = tmp_path / "corpus_native/manual/markdown"
    root.mkdir(parents=True)
    path = root / "guide.md"
    path.write_text("original")
    baseline.write_json(tmp_path / "corpus_manifest.json", {
        "files": [{"path": "manual/markdown/guide.md", "sha256": baseline.sha(b"original")}]
    })
    baseline.verify_corpus(tmp_path, "native")
    path.write_text("edited")
    with pytest.raises(ValueError, match="content changed"):
        baseline.verify_corpus(tmp_path, "native")
    path.write_text("original")
    (root / "extra.md").write_text("not in frozen scope")
    with pytest.raises(ValueError, match="file set changed"):
        baseline.verify_corpus(tmp_path, "native")
