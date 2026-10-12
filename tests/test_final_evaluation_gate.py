import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import final_evaluation_gate as gate


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def test_absolute_executable_preserves_virtualenv_symlink(tmp_path):
    real = tmp_path / "real-python"
    real.write_text("")
    launcher = tmp_path / "venv/bin/python"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(real)

    absolute = gate.absolute_executable(launcher)

    assert absolute == launcher.absolute()
    assert absolute != launcher.resolve()


def test_holdout_review_coverage_includes_mechanically_correctable_responses(tmp_path, monkeypatch):
    reviews = tmp_path / "reviews"
    write(reviews / "sessions/complete/compiled.json", {"review_count": 1})
    write(reviews / "sessions/complete/review-1.json", {})
    monkeypatch.setattr(gate.adjudication, "selection", lambda root, source: ["invalid"])

    assert gate.review_coverage(tmp_path / "run", reviews) == (2, 1)
    assert gate.missing_review_evidence(reviews) == []


def test_holdout_review_recovery_copies_compiled_response_evidence(tmp_path, monkeypatch):
    root = tmp_path / "run"
    base = tmp_path / "reviews"
    source = tmp_path / "reviews-recovery-v0"
    output = tmp_path / "output"
    write(base / "protocol.json", {"model": "deepseek-flash"})
    (base / "leaderboard_review.py").write_text("# frozen")
    write(source / "protocol.json", {"model": "deepseek-flash"})
    write(source / "sessions/complete/compiled.json", {"review_count": 2})
    write(source / "sessions/complete/review-1.json", {"response": 1})
    write(source / "sessions/complete/review-2.json", {"response": 2})
    write(source / "sessions/invalid/review-1.json", {"invalid": True})
    monkeypatch.setattr(gate.adjudication, "selection", lambda run, reviews: ["invalid"])

    def fake_call(command, log_root, label):
        target = Path(command[command.index("--output") + 1])
        write(target / "protocol.json", {"model": "deepseek-flash"})
        return 0

    monkeypatch.setattr(gate, "call", fake_call)
    target = gate.prepare_review_recovery(
        Path(sys.executable), root, base, source, output, "baseline", 1)

    assert gate.missing_review_evidence(target) == []
    assert (target / "sessions/complete/review-2.json").exists()
    assert (target / "sessions/invalid/review-1.json").exists()
    manifest = json.loads((target / "recovery-manifest.json").read_text())
    assert len(manifest["copied_compiled_response_evidence"]) == 2
