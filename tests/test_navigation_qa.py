"""问答评测的语料隔离、原文引用和失败计量，不访问模型或求解器。"""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from experiments.retrieval_method import navigation_dataset as ds
from experiments.retrieval_method import navigation_qa as qa
from experiments.retrieval_method import navigation_metrics as metrics


@pytest.fixture
def engine(tmp_path):
    lines = ["# Example", "", "pressure pRef 10;", "rho 2;", "", "another section", "pRef 20;"]
    path = tmp_path / "tutorials/demo/settings"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(lines) + "\n")
    return SimpleNamespace(files={"tutorials/demo/settings": lines}, corpus=tmp_path,
                           manifest={"tutorials/demo/settings": {"sha256": qa.digest(path.read_bytes())}})


def test_plain_search_and_read_measure_raw_work_and_repetition(engine):
    s = qa.Session(engine, "no_graph", "pressure")
    action = {"action": "search", "query": "pressure"}
    a, accounting = s.dispatch(action, 2000)
    assert a["items"] and accounting["content"]["file_search_scanned_files"] == 1
    assert accounting["content"]["file_search_scanned_characters"] > 0
    _, again = s.dispatch(action, 2000)
    assert again["repeat"] and again["content"] == accounting["content"]
    output, cost = s.dispatch({"action": "source", "path": "tutorials/demo/settings", "start": 3, "end": 4}, 2000)
    assert output["items"][0]["text"] == "pressure pRef 10;\nrho 2;"
    assert cost["content"]["source_file_read_operations"] == 1
    assert output["next_line"] is None


def test_no_graph_cannot_call_locator_and_source_confines_paths(engine):
    session = qa.Session(engine, "no_graph", "question")
    result, _ = session.dispatch({"action": "locate"}, 2000)
    assert result["status"] == "tool_error"
    result, _ = session.dispatch({"action": "source", "path": "../../outside"}, 2000)
    assert result["status"] == "tool_error"
    assert sum(session.calls.values()) == 2


def test_partial_preview_does_not_authorize_unseen_lines(engine):
    session = qa.Session(engine, "graph_optional", "question")
    session.observe({"locations": [{"path": "tutorials/demo/settings", "start": 3, "end": 4,
                                   "preview": "pressure pRef 10;\nrho", "preview_complete": False}]})
    assert session.seen == {"tutorials/demo/settings": {"3": "pressure pRef 10;"}}
    with pytest.raises(ValueError, match="differs"):
        session.observe({"items": [{"path": "tutorials/demo/settings", "start": 3, "end": 3,
                                    "text": "invented", "complete_range": True}]})


def test_source_read_rejects_changed_original(engine):
    (engine.corpus / "tutorials/demo/settings").write_text("changed\n")
    result, _ = qa.Session(engine, "no_graph", "question").dispatch(
        {"action": "source", "path": "tutorials/demo/settings", "start": 1, "end": 1}, 2000)
    assert result["status"] == "tool_error" and "changed" in result["reason"]


def test_dataset_rejects_derived_notes_and_solver_source():
    assert ds.source_kind("manual/markdown/05_fluid_solid_thermo.md") == "manual"
    for path in ("manual/markdown/98_reviewed_defaults.md", "manual/source_code/model.C", "manual/README.md"):
        with pytest.raises(ValueError, match="not original"):
            ds.source_kind(path)


def test_prompt_cannot_receive_gold_metadata():
    prompts = [qa.prompt(m) for m in qa.METHODS]
    assert all("Q013" not in p and "5e6" not in p and "annotations" not in p for p in prompts)
    assert "附加工具locate" not in prompts[0]
    assert "第一步使用locate" in prompts[2]


@pytest.mark.parametrize("inner", [
    {"action": "search", "query": "pressure"},
    json.dumps({"answer": "supported", "references": [], "unknowns": []}),
])
def test_choice_unwraps_exact_flash_json_object_transport_envelope(inner):
    wrapped = json.dumps({"type": "json_object", "content": inner})
    response = {"raw_response": {"model": "deepseek-flash", "choices": [
        {"finish_reason": "stop", "message": {"content": wrapped}}]}}
    content = qa.choice(response)["message"]["content"]
    parsed = json.loads(content)
    assert parsed.get("action") == "search" or parsed.get("answer") == "supported"


def test_choice_does_not_unwrap_answer_data_with_additional_fields():
    data = {"type": "json_object", "content": {"answer": "literal"}, "unknowns": []}
    response = {"raw_response": {"model": "deepseek-flash", "choices": [
        {"finish_reason": "stop", "message": {"content": json.dumps(data)}}]}}
    assert json.loads(qa.choice(response)["message"]["content"]) == data


def test_decode_json_prefix_accepts_flash_suffix_and_multiple_actions():
    first = {"action": "search", "query": "fieldMinMax"}
    dsml = json.dumps(first) + "\n\n<｜｜DSML｜｜ calls>duplicate rendering</｜｜DSML｜｜ calls>"
    multiple = json.dumps(first) + "\n" + json.dumps({"action": "catalog"})
    assert qa.decode_json_prefix(dsml) == first
    assert qa.decode_json_prefix(multiple) == first


def test_decode_json_prefix_accepts_literal_newline_inside_string():
    raw = '{"answer":"first line\nsecond line","references":[],"unknowns":[]}'
    assert qa.decode_json_prefix(raw)["answer"] == "first line\nsecond line"


def test_decode_json_prefix_repairs_only_premature_unescaped_string_quotes():
    raw = '{"answer":"use libs ("lib.so") here\nnext","references":[],"unknowns":[]}'
    assert qa.decode_json_prefix(raw)["answer"] == 'use libs ("lib.so") here\nnext'
    with pytest.raises(json.JSONDecodeError):
        qa.decode_json_prefix('{"answer":"x" "references":[]}')


def test_equivalent_flash_action_shapes_are_normalized():
    direct = {"action": "search", "query": "pressure"}
    assert qa.normalize_action(direct) is direct
    assert qa.normalize_action({"type": "locate", "query": "mesh"})["action"] == "locate"
    nested = qa.normalize_action({"type": "tool_call", "reason": "gap", "action": direct})
    assert nested == {"action": "search", "query": "pressure", "reason": "gap"}
    with_extra = qa.normalize_action({"type": "json_object", "action": direct, "answer": {"draft": True}})
    assert with_extra == direct
    assert qa.normalize_action([direct]) == {}


def test_length_capped_response_keeps_complete_first_action():
    complete = {'finish_reason': 'length', 'message': {'content':
        '{"action":"finish","reason":"enough"}\n{"answer":"unfinished'}}
    truncated_draft = {'finish_reason': 'length', 'message': {'content':
        '{"action":"finish","reason":"enough","answer":{"detail":"unfinished'}}
    tagged_truncated_draft = {'finish_reason': 'length', 'message': {'content':
        '{"type":"json_object","action":"finish","reason":"enough","answer":"unfinished'}}
    tagged_nested_missing_outer_close = {'finish_reason': 'stop', 'message': {'content':
        '{"type":"json_object","action":{"action":"finish","reason":"enough"}'}}
    assert qa.decode_action(complete) == {"action": "finish", "reason": "enough"}
    assert qa.decode_action(truncated_draft) == {"action": "finish"}
    assert qa.decode_action(tagged_truncated_draft) == {"action": "finish"}
    assert qa.decode_action(tagged_nested_missing_outer_close) == {"action": "finish", "reason": "enough"}
    assert qa.decode_action({'finish_reason': 'length', 'message': {'content': 'no json'}}) == {}


def test_final_answer_requires_shared_contract():
    assert qa.valid_answer({"answer": "x", "references": [], "unknowns": []})
    assert not qa.valid_answer({"action": "finish"})
    assert not qa.valid_answer({"answer": "x", "references": []})


def test_non_string_action_name_is_counted_as_invalid_instead_of_crashing(engine):
    result, _ = qa.Session(engine, "no_graph", "question").dispatch(
        {"action": {"action": "search", "query": "pressure"}}, 2000)
    assert result["status"] == "tool_error"


def test_resume_refuses_changed_request_and_invalid_received_response(tmp_path):
    body = qa.request([{"role": "user", "content": "question"}])
    qa.write(tmp_path / "step.json", {"status": "invalid_response", "request_sha256": qa.digest(qa.wire(body)),
                                     "events": [], "raw_text": "not json"})
    with pytest.raises(ValueError, match="no content retry"):
        qa.fetch(tmp_path, "step", body, "unused")
    with pytest.raises(ValueError, match="changed"):
        qa.fetch(tmp_path, "step", {**body, "temperature": 0.1}, "unused")


def test_freeze_gate_cannot_be_a_missing_path(tmp_path):
    args = SimpleNamespace(run=tmp_path/"holdout", split="holdout", freeze_gate=tmp_path/"missing.json")
    with pytest.raises(ValueError, match="existing frozen"):
        qa.prepare(args)
    assert not args.run.exists()


def test_citation_range_cannot_include_unseen_line():
    answer = {"references": [{"path": "example", "start": 3, "end": 5}]}
    seen = {"example": {"3": "a", "4": "b"}}
    assert not metrics.citation_check(answer, seen)[0]["valid_seen_range"]


def test_unknown_failed_api_usage_is_not_zero(tmp_path):
    folder = tmp_path / "Q001-p1--no_graph--r1"
    qa.write(folder / "step-01.json", {"status": "transport_error", "events": [
        {"status": "transport_error", "seconds": 0.2, "usage": None}]})
    annotation = {"id": "Q001", "category": "tutorial", "evidence": []}
    result = metrics.session_metrics(folder, annotation)
    assert result["transport_attempts"] == result["unknown_usage_attempts"] == 1
    assert result["all_attempts_model_tokens"] is None
    assert result["qa_success"] is None


def test_resume_uses_saved_tool_result_without_duplicate_search(tmp_path, engine, monkeypatch):
    engine.run = tmp_path
    question = {"id": "Q001-p1", "item_id": "Q001", "question": "pressure"}
    folder = tmp_path / "sessions/Q001-p1--no_graph--r1"
    tool = {"status": "ok", "items": [{"path": "tutorials/demo/settings", "start": 3, "end": 3,
                                         "text": "pressure pRef 10;", "complete_range": True}]}
    action = {"action": "search", "query": "pressure"}
    qa.write(folder / "tool_events/step-01.json", {"action": action, "result": tool,
        "accounting": {"seconds": 0.2, "content": {"file_search_scanned_characters": 100}, "repeat": False}})
    def fake_fetch(folder, name, body, key):
        content = qa.wire(action) if name == "step-01" else qa.wire({"action": "finish"}) if name == "step-02" else qa.wire({"answer": "10", "references": []})
        return {"raw_response": {"model": qa.MODEL, "choices": [{"finish_reason": "stop", "message": {"content": content}}]}}
    monkeypatch.setattr(qa, "fetch", fake_fetch)
    def forbidden_dispatch(*args):
        raise AssertionError("resume must reuse the saved tool output")
    monkeypatch.setattr(qa.Session, "dispatch", forbidden_dispatch)
    result = qa.run_one(engine, question, "no_graph", "unused")
    assert result["seen_lines"]["tutorials/demo/settings"]["3"] == "pressure pRef 10;"
    assert result["events"][0]["accounting"]["content"]["file_search_scanned_characters"] == 100
