from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from experiments.retrieval_method.graphify_query_backend import Attributes, METER, bounded_payload, original_paths
from experiments.retrieval_method import navigation_qa as base


def load_runner(monkeypatch):
    from experiments.retrieval_method import graphify_query_backend
    monkeypatch.setitem(sys.modules, "navigation_qa", base)
    monkeypatch.setitem(sys.modules, "graphify_query_backend", graphify_query_backend)
    path = Path(__file__).parents[1] / "experiments/retrieval_method/graphify_qa.py"
    spec = importlib.util.spec_from_file_location("isolated_graphify_qa", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_attributes_count_repeated_reads_without_changing_values():
    attrs = Attributes(label="abc", source="xyz")
    count = Counter()
    token = METER.set(count)
    try:
        assert attrs.get("label") == attrs["label"] == "abc"
        assert list(attrs.items()) == [("label", "abc"), ("source", "xyz")]
    finally:
        METER.reset(token)
    assert count["graph_attribute_read_operations"] == 4
    assert count["graph_attribute_read_characters"] == 12


def test_path_mapping_changes_only_provenance_fields_and_budget_is_hard():
    text = "NODE settings.txt [src=tutorials/demo/settings.txt loc=None]\nEDGE a --references--> b at=tutorials/demo/settings.txt:L3\n"
    mapped = original_paths(text, {"tutorials/demo/settings.txt": "tutorials/demo/settings"})
    assert "NODE settings.txt" in mapped
    assert "src=tutorials/demo/settings loc=None" in mapped
    assert "at=tutorials/demo/settings:L3" in mapped
    complete = bounded_payload(mapped, 1000, base.wire)
    assert not complete["truncated"]
    limited = bounded_payload(mapped * 100, 350, base.wire)
    assert limited["truncated"] and len(base.wire(limited)) <= 350
    assert (mapped * 100).startswith(limited["graph_navigation"])


def test_graph_labels_do_not_credit_original_evidence_and_plain_tools_match(tmp_path, monkeypatch):
    runner = load_runner(monkeypatch)
    relative = "tutorials/demo/settings"
    raw = "parameter 3;\ncondition yes;\n"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(raw)
    engine = SimpleNamespace(files={relative: raw.splitlines()}, corpus=tmp_path,
                             manifest={relative: {"sha256": base.digest(raw.encode())}},
                             inventory={relative: {}}, inverse={})
    reference = base.Session(engine, "no_graph", "parameter")
    actual = runner.Session(engine, "no_graph", "parameter")
    for action in ({"action": "search", "query": "parameter"},
                   {"action": "source", "path": relative, "start": 1, "end": 2}):
        expected, _ = reference.dispatch(action, 2000)
        result, _ = actual.dispatch(action, 2000)
        assert result == expected
    denied, _ = actual.dispatch({"action": "locate"}, 2000)
    assert denied["status"] == "tool_error"
    untouched = runner.Session(engine, "graph_optional", "parameter")
    untouched.observe({"status": "ok", "graph_navigation": f"NODE parameter [src={relative} loc=L1]"})
    assert untouched.seen == {}


def test_new_transport_preserves_identical_request_and_logs_before_send(tmp_path, monkeypatch):
    runner = load_runner(monkeypatch)
    runner.SECRET = "example-secret"
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"usage": {"total_tokens": 5}, "model": base.MODEL}).encode()
    calls = []
    def fake_urlopen(request, timeout):
        saved = json.loads((tmp_path / "step.json").read_text())
        assert saved["events"][-1]["status"] == "in_flight"
        assert "example-secret" not in (tmp_path / "step.json").read_text()
        calls.append(request)
        return Response()
    monkeypatch.setattr(runner, "urlopen", fake_urlopen)
    body = base.request([{"role": "user", "content": "question"}])
    response = runner.fetch(tmp_path, "step", body, "example-secret")
    assert response["status"] == "response" and len(calls) == 1
    assert runner.fetch(tmp_path, "step", body, None) == response
    with pytest.raises(ValueError, match="changed"):
        runner.fetch(tmp_path, "step", {**body, "model": "changed"}, None)


def test_interrupted_usage_stays_unknown_on_transport_resume(tmp_path, monkeypatch):
    runner = load_runner(monkeypatch)
    body = base.request([{"role": "user", "content": "q"}])
    base.write(tmp_path / "step.json", {"request": body, "request_sha256": base.digest(base.wire(body)),
        "status": "in_flight", "events": [{"status": "in_flight", "seconds": None, "usage": None}]})
    def failing(*args, **kwargs):
        raise runner.URLError("connection failed")
    monkeypatch.setattr(runner, "urlopen", failing)
    with pytest.raises(RuntimeError, match="transport_error"):
        runner.fetch(tmp_path, "step", body, "example-secret")
    saved = json.loads((tmp_path / "step.json").read_text())
    assert len(saved["events"]) == 4
    assert saved["events"][0]["status"] == "interrupted_unresolved"
    assert saved["events"][0]["seconds"] is None
    assert all(e["usage"] is None for e in saved["events"])


def test_global_network_outage_opens_process_circuit_before_grid_exhaustion(tmp_path, monkeypatch):
    runner = load_runner(monkeypatch)
    body = base.request([{"role": "user", "content": "q"}])
    calls = []

    def failing(*args, **kwargs):
        calls.append(1)
        raise runner.URLError("network unavailable")

    monkeypatch.setattr(runner, "urlopen", failing)
    with pytest.raises(RuntimeError, match="transport_error"):
        runner.fetch(tmp_path / "first", "step", body, "example-secret")
    with pytest.raises(runner.GlobalTransportOutage, match="circuit opened"):
        runner.fetch(tmp_path / "second", "step", body, "example-secret")
    with pytest.raises(runner.GlobalTransportOutage, match="circuit open"):
        runner.fetch(tmp_path / "third", "step", body, "example-secret")
    assert len(calls) == runner.TRANSPORT_OUTAGE_THRESHOLD == 4
    assert len(json.loads((tmp_path / "first/step.json").read_text())["events"]) == 3
    assert len(json.loads((tmp_path / "second/step.json").read_text())["events"]) == 1
    assert not (tmp_path / "third/step.json").exists()


def test_costs_count_repeated_context_and_preserve_unknown_durations(tmp_path):
    from experiments.retrieval_method import navigation_metrics as metrics
    folder = tmp_path / "Q001-p1--no_graph--r1"
    folder.mkdir()
    request = {"messages": [{"role": "user", "content": "Tool result: abc"}]}
    base.write(folder / "final.json", {"request": request, "status": "response",
        "events": [{"status": "interrupted_unresolved", "seconds": None, "usage": None},
                   {"status": "transport_error", "seconds": 2, "usage": None},
                   {"status": "response", "seconds": 3, "usage": {"total_tokens": 12, "completion_tokens": 2}}],
        "raw_response": {"usage": {"total_tokens": 12, "completion_tokens": 2}}})
    base.write(folder / "invocations/1.json", {"replay": False, "elapsed_seconds": None})
    base.write(folder / "invocations/2.json", {"replay": False, "elapsed_seconds": 7})
    base.write(folder / "invocations/3.json", {"replay": True, "elapsed_seconds": 900})
    result = metrics.session_metrics(folder, {"id": "Q001", "category": "tutorial", "evidence": []})
    assert result["reported_total_model_tokens"] == 12
    assert result["all_attempts_model_tokens"] is None
    assert result["transport_retries"] == 2
    assert result["unknown_usage_attempts"] == 2
    assert result["api_seconds"] == 5 and result["unknown_api_duration_attempts"] == 1
    assert result["session_seconds"] == 7 and result["all_invocations_session_seconds"] is None
    assert result["attempted_request_content"]["tool_context_message_characters"] == 3 * len("Tool result: abc")


def test_invalid_graph_query_cannot_reuse_previous_query_audit(tmp_path, monkeypatch):
    runner = load_runner(monkeypatch)
    engine = SimpleNamespace(files={})
    session = runner.Session(engine, "graph_first", "question")
    session.graph_audits.append({"raw_native_return": "previous query"})
    result, accounting = session.dispatch({"action": "locate", "translation": []}, 2000)
    assert result["status"] == "tool_error"
    assert accounting["native_query_audit"] is None


def test_runtime_identity_rejects_seed_or_interpreter_drift(monkeypatch):
    runner = load_runner(monkeypatch)
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    protocol = {"runtime_identity": runner.runtime_identity()}
    runner.verify_runtime(protocol)
    monkeypatch.setenv("PYTHONHASHSEED", "1")
    with pytest.raises(ValueError, match="PYTHONHASHSEED"):
        runner.verify_runtime(protocol)
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    protocol["runtime_identity"]["hash_probe"] += 1
    with pytest.raises(ValueError, match="interpreter"):
        runner.verify_runtime(protocol)
