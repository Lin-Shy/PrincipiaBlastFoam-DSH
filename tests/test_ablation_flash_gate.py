import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import ablation_flash_gate as gate
from ablation_flash_gate import (
    admitted_replay_checkpoint,
    compiled_review_count,
    missing_compiled_review_evidence,
    next_recovery_path,
    review_resolution_coverage,
)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def test_admitted_replay_checkpoint_requires_complete_protocol_bound_grid(tmp_path):
    root = tmp_path / "run"
    followup = tmp_path / "followup"
    protocol = root / "protocol.json"
    write_json(protocol, {"planned_sessions": 12})
    import hashlib

    digest = hashlib.sha256(protocol.read_bytes()).hexdigest()
    write_json(
        followup / "admission.json",
        {
            "passed": True,
            "protocol_sha256": digest,
            "expected": 12,
            "answers": 11,
            "terminal_failures": 1,
            "replayed": 11,
            "provider_models": {"deepseek-flash": 24},
            "errors": [],
        },
    )

    assert admitted_replay_checkpoint(root, followup, revalidate=False)


def test_admitted_replay_checkpoint_rejects_drift_or_partial_replay(tmp_path):
    root = tmp_path / "run"
    followup = tmp_path / "followup"
    protocol = root / "protocol.json"
    write_json(protocol, {"planned_sessions": 12})
    write_json(
        followup / "admission.json",
        {
            "passed": True,
            "protocol_sha256": "wrong",
            "expected": 12,
            "answers": 11,
            "terminal_failures": 1,
            "replayed": 10,
            "provider_models": {"deepseek-flash": 24},
            "errors": [],
        },
    )

    assert not admitted_replay_checkpoint(root, followup, revalidate=False)


def test_review_recovery_helpers_count_compiled_and_allocate_new_generation(tmp_path):
    base = tmp_path / "candidate_ablation_flash_v1"
    compiled = base / "sessions" / "one" / "compiled.json"
    write_json(compiled, {"status": "reviewed"})
    (tmp_path / "candidate_ablation_flash_v1_recovery_v1").mkdir()

    assert compiled_review_count(base) == 1
    assert next_recovery_path(base, "recovery") == (
        tmp_path / "candidate_ablation_flash_v1_recovery_v2",
        2,
    )


def test_review_resolution_coverage_includes_structurally_invalid_for_adjudication(tmp_path, monkeypatch):
    reviews = tmp_path / "reviews"
    write_json(reviews / "sessions" / "compiled" / "compiled.json", {"status": "reviewed"})
    monkeypatch.setattr(gate.adjudication, "selection", lambda root, parent: {"invalid": {}})

    assert review_resolution_coverage(tmp_path / "run", reviews) == (2, 1)


def test_compiled_review_requires_all_accepted_response_evidence(tmp_path):
    reviews = tmp_path / "reviews"
    session = reviews / "sessions" / "one"
    write_json(session / "compiled.json", {"review_count": 2})
    write_json(session / "review-1.json", {"response": 1})

    assert missing_compiled_review_evidence(reviews) == ["one"]

    write_json(session / "review-2.json", {"response": 2})
    assert missing_compiled_review_evidence(reviews) == []
