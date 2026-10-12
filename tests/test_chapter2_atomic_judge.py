from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

SOURCE = Path(__file__).parents[1] / "experiments/retrieval_method"
sys.path.insert(0, str(SOURCE))
import chapter2_atomic_judge as atomic
from chapter2_augmentation_evaluation import semantic_bounds


def test_reference_index_cannot_replace_actual_answer_claim():
    with pytest.raises(ValueError, match="absent"):
        atomic.validate_item({"actual_answer_quote": "gold", "assessment": "satisfied", "claim_indices": [2], "reason": "reference says so"}, "fact", [{"index": 0, "text": "unknown"}])
    with pytest.raises(ValueError, match="assignment"):
        atomic.validate_item({"actual_answer_quote": "gold", "assessment": "satisfied", "claim_indices": [], "reason": "gold is correct"}, "fact", [])


def test_empty_answer_does_not_send_gold_to_judge(tmp_path):
    calls = []
    core = SimpleNamespace(sha=lambda _: "session-hash")
    evaluation = SimpleNamespace(reference_packet=lambda *_: {"answer": {"claims": []}})
    result = atomic.score_session(core, evaluation, {}, {}, {"status": "complete_structure"}, tmp_path / "session.json",
                                  lambda *args: calls.append(args), tmp_path)
    assert calls == []
    assert result["bounds"]["answer_complete"] == [0., 0.]
    assert result["bounds"]["citation_support"] == [0., 1.]


def test_invalid_one_item_does_not_discard_known_failure(monkeypatch, tmp_path):
    packet = {"answer": {"claims": [{"text": "实际写出的答案"}]}, "question": "问题", "gold": ["需求1", "需求2"],
              "reference_evidence": [], "allowed": [], "forbidden": [], "citations": []}
    returns = iter([({"actual_answer_quote": "", "assessment": "missing", "claim_indices": [], "reason": "缺少需求1"}, None),
                    (None, "invalid schema"), ({"error_claim_indices": [], "uncertain": False, "reason": "无额外错误"}, None)])
    monkeypatch.setattr(atomic, "judge_item", lambda *args: next(returns))
    result = atomic.score_session(SimpleNamespace(sha=lambda _: "hash"),
                                 SimpleNamespace(reference_packet=lambda *_: packet, semantic_bounds=semantic_bounds),
                                 {}, {}, {"status": "complete_structure"}, tmp_path / "session.json", None, tmp_path)
    assert result["status"] == "partial_unknown"
    assert result["bounds"]["fact_coverage"] == [0., .5]
    assert result["bounds"]["answer_complete"] == [0., 0.]
    assert result["judgment"]["requirements"][0]["assessment"] == "missing"


def test_citation_evaluation_rejects_extra_gold_fields():
    with pytest.raises(ValueError, match="schema"):
        atomic.validate_item({"support": "supported", "reason": "yes", "requirements": []}, "citation", [])


def test_actual_claim_assignments_are_unique():
    with pytest.raises(ValueError, match="absent"):
        atomic.validate_item({"actual_answer_quote": "x", "assessment": "satisfied", "claim_indices": [0, 0], "reason": "same"}, "fact", [{"index": 0, "text": "x"}])


def test_copied_gold_cannot_pass_as_actual_answer_quote():
    with pytest.raises(ValueError, match="absent"):
        atomic.validate_item({"actual_answer_quote": "Euler", "assessment": "satisfied", "claim_indices": [0], "reason": "gold says Euler"},
                             "fact", [{"index": 0, "text": "无法回答"}])


def test_judge_model_change_is_validated_in_scoring_process_only(tmp_path):
    revision = {"judge_model": "qwen3-14b", "max_output_tokens_per_item": 700}
    original_usage = lambda _: "original"
    core = SimpleNamespace(load=lambda _: revision, usage=original_usage)
    atomic.configure_judge(core, tmp_path)
    assert core.atomic_judge_model == "qwen3-14b"
    response = {"model": "qwen3-14b", "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    assert core.usage(response) == [100, 20]
    assert response["model"] == "qwen3-14b"
    with pytest.raises(ValueError, match="model identity"):
        core.usage({**response, "model": "qwen3-8b"})
    with pytest.raises(ValueError, match="usage"):
        core.usage({"model": "qwen3-14b", "usage": {"prompt_tokens": True, "completion_tokens": 20}})
