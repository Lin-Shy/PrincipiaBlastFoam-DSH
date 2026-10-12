"""离线验证共享工具、证据预算、评分边界与族统计，不调用付费模型。"""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))
import chapter2_augmentation as runner
import chapter2_augmentation_evaluation as evaluation


@pytest.fixture
def corpus(tmp_path):
    source = tmp_path / "corpus"
    (source / "manual").mkdir(parents=True)
    (source / "tutorials").mkdir()
    text = "# Model\nalpha 1;\nbeta 2;\n"
    (source / "manual/a.md").write_text(text)
    (source / "tutorials/b").write_text("alpha 3;\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {str(p.relative_to(source)): runner.sha(p) for p in source.rglob("*") if p.is_file()}}))
    return {"corpus": str(source), "inputs": {"corpus_manifest": {"path": str(manifest)}}}


def response(message, finish="stop"):
    return {"model": "qwen3-8b", "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "choices": [{"finish_reason": finish, "message": message}]}


def test_base_tools_identical_and_no_other_backend_leak(corpus):
    base = runner.tools_for("grep")
    for arm in runner.ARMS:
        assert runner.tools_for(arm)[:3] == base
        session = runner.ToolSession(corpus, arm)
        assert session.engine is None
        assert session.execute("locate_files", {"pattern": "*"}) == runner.ToolSession(corpus, "grep").execute("locate_files", {"pattern": "*"})
    with pytest.raises(ValueError, match="not enabled"):
        runner.ToolSession(corpus, "grep_graph").execute("bm25_search", {"query": "alpha"})


def test_manifest_path_hash_and_coordinate_integrity(corpus):
    session = runner.ToolSession(corpus, "grep")
    with pytest.raises(ValueError):
        session.execute("read_source", {"path": "../manifest.json", "start": 1, "end": 1})
    with pytest.raises(ValueError):
        session.execute("read_source", {"path": "manual/a.md", "start": True, "end": 1})
    text = session.execute("read_source", {"path": "manual/a.md", "start": 2, "end": 2})
    assert "2: alpha 1;" in text
    assert session.units[0]["start"] == session.units[0]["end"] == 2
    (Path(corpus["corpus"]) / "manual/a.md").write_text("drift")
    with pytest.raises(ValueError, match="drift"):
        session.execute("grep", {"query": "alpha"})


def test_cross_call_dedup_partial_line_readable_later(corpus, monkeypatch):
    session = runner.ToolSession(corpus, "grep")
    header = len(f"\n[S1] manual/a.md sha256={runner.sha(Path(corpus['corpus']) / 'manual/a.md')} requested_lines=1-3\n")
    monkeypatch.setitem(runner.LIMITS, "tool_characters", header + len("1: # Model\n"))
    session.execute("read_source", {"path": "manual/a.md", "start": 1, "end": 3})
    assert session.units[0]["end"] == 1
    monkeypatch.setitem(runner.LIMITS, "tool_characters", 6000)
    session.execute("read_source", {"path": "manual/a.md", "start": 1, "end": 3})
    assert session.units[1]["start"] == 2
    size = session.new_characters
    session.execute("read_source", {"path": "manual/a.md", "start": 1, "end": 3})
    assert session.new_characters == size
    assert len(session.units) == 2
    assert len(session.events) == 3


def test_native_tool_loop_uses_base_and_enhancement_option(corpus, tmp_path):
    requests = []
    calls = [response({"role": "assistant", "content": json.dumps({"action": "tool", "name": "grep", "arguments": {"query": "alpha", "path_glob": "manual/*"}})}),
             response({"role": "assistant", "content": json.dumps({"action": "final", "answer": {"claims": [{"text": "alpha 1;", "citations": [{"source": "S1", "start": 2, "end": 2}]}], "unresolved": []}})})]
    def fetch(req, folder, label):
        requests.append(json.loads(json.dumps(req)))
        return calls.pop(0)
    record = runner.run_session(corpus, "grep_bm25", {"question": "alpha?"}, fetch, tmp_path)
    assert record["status"] == "complete_structure"
    assert record["input_tokens"] == 200
    assert record["tool_calls"] == 1
    assert requests[1]["messages"][-1]["role"] == "user"
    assert "bm25_search" in requests[0]["messages"][0]["content"]
    assert "tools" not in requests[0]


def test_parallel_calls_fail_and_budget_forces_final(corpus, tmp_path, monkeypatch):
    call = {"id": "c1", "type": "function", "function": {"name": "grep", "arguments": '{"query":"alpha"}'}}
    record = runner.run_session(corpus, "grep", {"question": "alpha"}, lambda *_: response({"tool_calls": [call, call]}, "tool_calls"), tmp_path)
    assert record["error"] == "unexpected_native_tool_call_in_json_action_protocol"
    monkeypatch.setitem(runner.LIMITS, "tool_calls", 0)
    requests = []
    def final(req, *_):
        requests.append(req)
        return response({"content": '{"action":"final","answer":{"claims":[],"unresolved":["证据不足"]}}'})
    record = runner.run_session(corpus, "grep", {"question": "alpha"}, final, tmp_path)
    assert "tools" not in requests[0]
    assert record["status"] == "complete_structure"


def test_failed_transport_retains_failure_without_invented_usage(corpus, tmp_path):
    def fetch(*_):
        raise runner.TransportFailure("network")
    record = runner.run_session(corpus, "grep", {"question": "alpha"}, fetch, tmp_path)
    assert record["status"] == "failed"
    assert record["input_tokens"] == 0
    assert "unknown" in record["error"]
    with pytest.raises(ValueError, match="missing"):
        runner.usage({"usage": {}})


def test_context_headroom_finalizes_before_another_tool(corpus, tmp_path, monkeypatch):
    original = runner.input_bound
    def bounded(req):
        if len(req["messages"]) >= 4:
            return 22000
        return original(req)
    monkeypatch.setattr(runner, "input_bound", bounded)
    requests = []
    def fetch(req, *_):
        requests.append(req)
        if len(requests) == 1:
            action = {"action": "tool", "name": "grep", "arguments": {"query": "alpha", "path_glob": "manual/*"}}
        else:
            action = {"action": "final", "answer": {"claims": [{"text": "alpha 1;", "citations": [{"source": "S1", "start": 2, "end": 2}]}], "unresolved": []}}
        return response({"content": json.dumps(action)})
    record = runner.run_session(corpus, "grep", {"question": "alpha"}, fetch, tmp_path)
    assert record["status"] == "complete_structure"
    assert record["tool_calls"] == 1
    assert record["trace"][-1]["forced_final"]


def judgment(assessment="satisfied", support="supported"):
    return {"requirements": [{"index": 0, "assessment": assessment, "actual_answer_quote": "alpha 1;", "reason": "匹配原文"}],
            "citations": [{"index": 0, "support": support, "reason": "原文支持"}],
            "extra_errors": [], "extra_errors_uncertain": False}


def test_judge_missing_wrong_scope_and_unknown_are_not_passes():
    packet = {"gold": ["alpha 1;"], "citations": [{}], "answer": {"claims": [{"text": "alpha 1;"}]}}
    assert evaluation.semantic_bounds(evaluation.validate_judge(judgment(), packet), 1)["answer_complete"] == [1., 1.]
    for assessment in ("partial", "missing", "incorrect"):
        assert evaluation.semantic_bounds(judgment(assessment), 1)["answer_complete"] == [0., 0.]
    assert evaluation.semantic_bounds(judgment("uncertain"), 1)["answer_complete"] == [0., 1.]
    assert evaluation.semantic_bounds(judgment(support="unsupported"), 1)["citation_support"] == [0., 0.]
    value = judgment()
    value["requirements"][0]["actual_answer_quote"] = "model invented answer"
    with pytest.raises(ValueError, match="not in actual"):
        evaluation.validate_judge(value, packet)
    value = judgment()
    value["requirements"].append(dict(value["requirements"][0]))
    with pytest.raises(ValueError, match="extra"):
        evaluation.validate_judge(value, packet)


def test_holm_and_family_sign_test():
    assert evaluation.sign_test([1, 1, 1, 1, 0]) == 1 / 16
    assert evaluation.sign_test([0, 0]) == 1
    assert evaluation.holm({"a": .01, "b": .04, "c": .05}) == {"a": .03, "b": .08, "c": .08}


def test_request_token_limit_blocks_network(tmp_path, monkeypatch):
    settings = tmp_path / "settings"
    settings.write_text('QWEN_PROXY_BASE_URL=https://proxy.example.test/v1\nQWEN_PROXY_API_KEY=test\n')
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *_: pytest.fail("oversized request must not reach network"))
    req = runner.request([{"role": "user", "content": "x" * 30000}], "grep")
    with pytest.raises(ValueError, match="input limit"):
        runner.Provider(tmp_path, settings)(req, tmp_path / "runs", "turn-00")


def test_full_offline_answer_score_report_and_missing_denominator(corpus, tmp_path):
    root = tmp_path / "archive"
    q = {"id": "F1-n1", "family_id": "F1", "question": "alpha?"}
    runner.save(root / "public/dev.questions.json", [q])
    protocol = {**corpus, "inputs": {**corpus["inputs"], "dev_questions": {"path": str(root / "public/dev.questions.json")}}}
    runner.save(root / "protocol.json", protocol)
    annotation = {"id": "F1", "gold": ["alpha 1;"], "allowed": [], "forbidden": [],
                  "evidence": [{"path": "manual/a.md", "start": 2, "end": 2, "quote": "alpha 1;",
                                "sha256": runner.sha(Path(corpus["corpus"]) / "manual/a.md")}]}
    runner.save(root / "evaluation_only/dev.annotations.json", [annotation])
    runner.save(root / "evaluation_only/review-sample.json", {"families": ["F1"]})
    first = evaluation.report(root, protocol, "dev")
    assert first["planned_rows"] == 12 and len(first["missing"]) == 12
    assert "comparisons" not in first
    for _, repeat, arm, session_path in evaluation.grid(root, protocol, "dev"):
        session = runner.ToolSession(protocol, arm)
        session.execute("read_source", {"path": "manual/a.md", "start": 2, "end": 2})
        answer = {"claims": [{"text": "alpha 1;", "citations": [{"source": "S1", "start": 2, "end": 2}]}], "unresolved": []}
        record = {"status": "complete_structure", "answer": answer, "delivery": session.units, "tools": session.events,
                  "question": q, "repeat": repeat, "arm": arm, "input_tokens": 100, "output_tokens": 50,
                  "tool_calls": 1, "wall_seconds": .1, "protocol_sha256": runner.sha(root / "protocol.json")}
        runner.save(session_path, record)
        score = evaluation.judge_session(root, protocol, annotation, record, session_path,
                                        lambda *_: response({"content": json.dumps(judgment())}), session_path.parent)
        assert score["status"] == "scored"
        file = root / "evaluation_only/scores/dev" / q["id"] / f"r{repeat}" / arm / "score.json"
        runner.save(file, {**score, "protocol_sha256": runner.sha(root / "protocol.json")})
    final = evaluation.report(root, protocol, "dev")
    assert final["status"] == "complete" and final["observed_rows"] == 12
    assert all(s["independent_families"] == 1 for s in final["summary"].values())
    assert final["summary"]["grep_graph"]["answer_complete"] == [1., 1.]
    assert final["summary"]["grep_graph"]["enhancement_used"] == 0  # 不能只选实际用增强工具的会话。
    assert not final["comparisons"]["grep_graph"]["answer_quality_improvement_supported"]


def test_production_guard_blocks_gold_and_external_process(tmp_path):
    import subprocess
    gold = tmp_path / "evaluation_only/test.annotations.json"
    gold.parent.mkdir()
    gold.write_text('[]')
    script = f"""from pathlib import Path
from chapter2_production_guard import install
install(offline=True,allow_test_public=True)
try:
 Path({str(gold)!r}).read_text()
except PermissionError:
 print('blocked')
else:
 raise AssertionError('gold leak')
"""
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(runner.__file__).parent)}
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "blocked"


def test_proxy_provider_provenance_without_monetary_gate(tmp_path, monkeypatch):
    import io
    settings = tmp_path / "settings"
    settings.write_text('QWEN_PROXY_BASE_URL=https://proxy.example.test/v1\nQWEN_PROXY_API_KEY=private-test-credential\n')
    def open_fake(req, **kwargs):
        assert req.full_url == 'https://proxy.example.test/v1/chat/completions'
        return io.StringIO(json.dumps(response({"content": '{}'})))
    monkeypatch.setattr(runner.urllib.request, "urlopen", open_fake)
    fetch = runner.Provider(tmp_path, settings)
    request = runner.request([{"role": "user", "content": "question"}], "grep")
    fetch(request, tmp_path / "runs", "turn-00")
    saved = runner.load(tmp_path / "runs/turn-00.json")
    assert saved["provider"] == "qwen_proxy"
    for file in (tmp_path / "runs").glob('*.json'):
        assert 'private-test-credential' not in file.read_text()
    assert not (tmp_path / 'accounting').exists()
    replay = fetch(request, tmp_path / "runs", "turn-00")
    assert '_replayed_seconds' in replay


def test_cleanup_keeps_bound_cache_and_removes_only_regenerable_cache(tmp_path):
    import chapter2_augmentation_cleanup as cleanup
    source = tmp_path / "source"
    source.mkdir()
    cache = source / "__pycache__"
    cache.mkdir()
    (source / "keep.py").write_text('pass\n')
    (source / "remove.py").write_text('pass\n')
    keep = cache / "keep.cpython-313.pyc"
    remove = cache / "remove.cpython-313.pyc"
    keep.write_bytes(b'bound cache')
    remove.write_bytes(b'regenerable cache')
    (source / "seal.json").write_text(json.dumps({'hash': cleanup.digest(keep)}))
    output = tmp_path / "cleanup.json"
    cleanup.audit([source], output, apply=True)
    assert keep.exists() and not remove.exists()
    assert (source / "remove.py").exists()
    completion = runner.load(output.with_suffix('.completion.json'))
    assert completion['removed_count'] == 1
