from copy import deepcopy

import pytest

import json

from experiments.retrieval_method.navigation_dev_revision import blob, build, sha, transform, verify_files


def sample():
    questions = [{"id": "Q001-p1", "item_id": "Q001", "question": "old"},
                 {"id": "Q001-p2", "item_id": "Q001", "question": "unchanged"}]
    revision = {"version": "dev-test", "reason": "clarify scope", "observed_development_results": True,
                "patches": {"Q001-p1": {"before": "old", "after": "new", "reason": "scope omitted"}}}
    return questions, revision


def test_question_only_revision_preserves_inputs_ids_and_unmodified_variants():
    questions, revision = sample()
    previous = deepcopy(questions)
    result = transform(questions, revision)
    assert questions == previous
    assert result == [{"id": "Q001-p1", "item_id": "Q001", "question": "new"}, previous[1]]


@pytest.mark.parametrize("change", ["observation", "old_text", "gold", "unknown", "duplicate"])
def test_revision_rejects_undeclared_observation_or_scope_change(change):
    questions, revision = sample()
    patch = revision["patches"]["Q001-p1"]
    if change == "observation": revision["observed_development_results"] = False
    elif change == "old_text": patch["before"] = "not the parent"
    elif change == "gold": patch["gold"] = ["new answer"]
    elif change == "unknown": revision["patches"]["H001-p1"] = deepcopy(patch)
    else: patch["after"] = "unchanged"
    with pytest.raises(ValueError):
        transform(questions, revision)


def test_frozen_paths_cannot_escape_root(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"not dataset")
    with pytest.raises(ValueError, match="mismatch"):
        verify_files(root, {"../outside": sha(b"not dataset")})


def fixture_parents(tmp_path):
    parent = tmp_path / "parent"
    baseline = tmp_path / "baseline"
    parent.mkdir()
    (baseline / "control/evaluation_only").mkdir(parents=True)
    questions, revision = sample()
    artifacts = {"dev.questions.json": blob(questions),
        "dev.annotations.json": blob([{"id": "Q001", "category": "tutorial", "split": "dev"}]),
        "scoring-rules.json": blob({"version": "unchanged"}),
        # Invalid JSON deliberately proves that holdout contents are only hashed.
        "holdout.questions.json": b"do not parse holdout", "holdout.annotations.json": b"also not JSON"}
    for name, raw in artifacts.items():
        (parent / name).write_bytes(raw)
    (parent / "manifest.json").write_bytes(blob({"artifacts": {n: sha(r) for n, r in artifacts.items()}}))
    frozen = {"control/questions.json": artifacts["dev.questions.json"],
        "control/evaluation_only/annotations.json": artifacts["dev.annotations.json"],
        "control/evaluation_only/scoring-rules.json": artifacts["scoring-rules.json"],
        "control/corpus-manifest.json": blob({"raw.txt": {"sha256": "source"}})}
    for name, raw in frozen.items():
        (baseline / name).write_bytes(raw)
    (baseline / "protocol.json").write_bytes(blob({"corpus_id": "common-scope", "files": {n: sha(r) for n, r in frozen.items()}}))
    (baseline / "metrics.json").write_bytes(b"observed dev report")
    revision["observed_metrics"] = {"file": "metrics.json", "sha256": sha(b"observed dev report")}
    authored = tmp_path / "revision.json"
    authored.write_bytes(blob(revision))
    return parent, baseline, authored


def test_build_is_dev_only_and_gold_is_byte_identical(tmp_path):
    parent, baseline, authored = fixture_parents(tmp_path)
    output = tmp_path / "new_version"
    build(parent, baseline, authored, output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["source_files"] == 1
    assert manifest["parent_holdout_artifact_sha256"]
    assert not list(output.glob("holdout*"))
    assert (output / "dev.annotations.json").read_bytes() == (parent / "dev.annotations.json").read_bytes()
    assert (output / "scoring-rules.json").read_bytes() == (parent / "scoring-rules.json").read_bytes()
    with pytest.raises(FileExistsError):
        build(parent, baseline, authored, output)


def test_build_rejects_parent_drift_before_creating_output(tmp_path):
    parent, baseline, authored = fixture_parents(tmp_path)
    (parent / "dev.annotations.json").write_bytes(b"changed gold")
    output = tmp_path / "new_version"
    with pytest.raises(ValueError, match="mismatch"):
        build(parent, baseline, authored, output)
    assert not output.exists()
