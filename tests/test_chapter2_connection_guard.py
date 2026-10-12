import http.client
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments/retrieval_method"))
from chapter2_connection_guard import guarded_open


def test_disconnect_enters_existing_network_error_branch_without_internal_retry(tmp_path):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise http.client.RemoteDisconnected("connection closed")
    req = urllib.request.Request("https://example.invalid", b'{"model":"qwen3-8b"}', {"Authorization": "Bearer SECRET"})
    with pytest.raises(urllib.error.URLError) as e:
        guarded_open(fail, tmp_path)(req)
    assert isinstance(e.value.reason, http.client.RemoteDisconnected)
    assert len(calls) == 1
    record = next(tmp_path.glob("*.json")).read_text()
    assert "SECRET" not in record and "Authorization" not in record
    assert json.loads(record)["usage_unknown"] is True


def test_interrupted_response_read_uses_same_network_error_branch(tmp_path):
    class Response:
        def read(self):
            raise ConnectionResetError("reset")
    req = urllib.request.Request("https://example.invalid", b"{}")
    response = guarded_open(lambda *_: Response(), tmp_path)(req)
    with pytest.raises(urllib.error.URLError):
        response.read()
    assert len(list(tmp_path.glob("*.json"))) == 1
