import json
from pathlib import Path
import sys

SOURCE = Path(__file__).parents[1] / "experiments/retrieval_method"
sys.path.insert(0, str(SOURCE))
import chapter2_augmentation as core
import chapter2_transport_recovery as recovery


def test_recovery_targets_failed_second_request_and_replays_existing_first(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    core.save(root / "protocol.json", {"model": "qwen3-8b"})
    folder = root / "evaluation_only/scores/test/Q1/r1/grep"
    core.save(folder / "score.json", {"status": "unknown", "error": "judge_transport_exhausted; unknown retained"})
    core.save(folder / "judge-0.json", {"received": "first response must be preserved"})
    core.save(folder / "judge-1.attempt-0.json", {"request_sha256": "failed-second-request-hash"})
    schema_failure = root / "evaluation_only/scores/test/Q2/r1/grep/score.json"
    core.save(schema_failure, {"status": "unknown", "error": "missing or extra judge items"})
    exporter = tmp_path / "build_report.py"
    exporter.write_text("# fixture")
    monkeypatch.setattr(core, "verify", lambda _: {})
    revision = tmp_path / "revision"
    recovery.prepare(core, root, revision, exporter)
    spec = core.load(revision / "protocol.json")
    assert len(spec["targets"]) == 1
    target = spec["targets"][0]
    assert target["original_failed_label"] == "judge-1"
    assert target["original_request_sha256"] == "failed-second-request-hash"
    assert target["successful_responses_sha256"]["judge-0.json"] == core.sha(folder / "judge-0.json")
    assert (revision / "canonical_view/evaluation_only/scores/test/Q2/r1/grep/score.json").resolve() == schema_failure
    assert spec["maximum_original_plus_recovery_attempts_per_request"] == 6
    assert core.load(folder / "judge-0.json")["received"] == "first response must be preserved"


def test_recovery_targets_original_first_request_when_no_response_arrived(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    core.save(root / "protocol.json", {"model": "qwen3-8b"})
    folder = root / "evaluation_only/regrades/test/Q1/r1/grep"
    core.save(folder / "score.json", {"status": "unknown", "error": "judge_transport_exhausted; unknown retained"})
    core.save(folder / "judge-0.attempt-0.json", {"request_sha256": "first-request-hash"})
    exporter = tmp_path / "build_report.py"
    exporter.write_text("# fixture")
    monkeypatch.setattr(core, "verify", lambda _: {})
    revision = tmp_path / "revision"
    recovery.prepare(core, root, revision, exporter)
    target = core.load(revision / "protocol.json")["targets"][0]
    assert target["stage"] == "regrades"
    assert target["original_failed_label"] == "judge-0"
    assert target["successful_responses_sha256"] == {}
    assert target["original_request_sha256"] == "first-request-hash"
