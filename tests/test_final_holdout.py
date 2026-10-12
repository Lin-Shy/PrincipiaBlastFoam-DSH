import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import final_holdout
from final_holdout import copy_arm, prepare


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value))
    else:
        path.write_text(value)


def test_copy_arm_preserves_frozen_runtime_and_replaces_only_holdout_inputs(tmp_path):
    source = tmp_path / "source"
    write(source / "questions.json", [{"id": "DEV"}])
    write(source / "evaluation_only/annotations.json", [{"id": "DEV"}])
    write(source / "evaluation_only/scoring-rules.json", {"version": "dev"})
    write(source / "skill/corpus/source.txt", "frozen corpus")
    files = {p.relative_to(source).as_posix(): digest(p)
             for p in source.rglob("*") if p.is_file()}
    write(source / "protocol.json", {"schema": "arm", "arm": "old",
          "methods": ["old"], "files": files, "split": "dev", "replicates": 3})
    questions = tmp_path / "holdout.questions.json"
    annotations = tmp_path / "holdout.annotations.json"
    scoring = tmp_path / "scoring-rules.json"
    write(questions, [{"id": "HOLDOUT"}])
    write(annotations, [{"id": "HOLDOUT"}])
    write(scoring, {"version": "holdout"})

    target = tmp_path / "target"
    copy_arm(source, target, questions, annotations, scoring, "selected", ["graph_first"], "dataset-sha")

    protocol = json.loads((target / "protocol.json").read_text())
    assert json.loads((target / "questions.json").read_text())[0]["id"] == "HOLDOUT"
    assert (target / "skill/corpus/source.txt").read_text() == "frozen corpus"
    assert protocol["arm"] == "selected"
    assert protocol["methods"] == ["graph_first"]
    assert protocol["split"] == "holdout"
    assert protocol["dataset_manifest_sha256"] == "dataset-sha"
    assert all(digest(target / name) == expected for name, expected in protocol["files"].items())


def test_prepare_unlocks_only_a_gate_bound_parent_holdout(tmp_path):
    dataset = tmp_path / "parent"
    write(dataset / "holdout.questions.json", [{"id": "H1", "item_id": "H", "question": "q"}])
    write(dataset / "holdout.annotations.json", [{"id": "H", "category": "manual"}])
    write(dataset / "scoring-rules.json", {"rule": 1})
    artifacts = {p.name: digest(p) for p in dataset.iterdir() if p.is_file()}
    write(dataset / "manifest.json", {"artifacts": artifacts})

    dev_dataset = tmp_path / "dev"
    write(dev_dataset / "manifest.json", {
        "parent_dataset": str(dataset),
        "parent_manifest_sha256": digest(dataset / "manifest.json"),
        "parent_holdout_artifact_sha256": {
            "holdout.questions.json": digest(dataset / "holdout.questions.json"),
            "holdout.annotations.json": digest(dataset / "holdout.annotations.json")}})

    baseline = tmp_path / "baseline"
    for arm, method in (("control", "no_graph"), ("GN", "graph_first")):
        source = baseline / arm
        write(source / "questions.json", [{"id": "D1"}])
        write(source / "evaluation_only/annotations.json", [{"id": "D"}])
        write(source / "evaluation_only/scoring-rules.json", {"rule": 1})
        write(source / "skill/corpus/source.txt", "corpus")
        files = {p.relative_to(source).as_posix(): digest(p)
                 for p in source.rglob("*") if p.is_file()}
        write(source / "protocol.json", {"arm": arm, "methods": [method], "files": files,
              "model": "deepseek-flash", "split": "dev", "replicates": 3})
    runtime = {"pythonhashseed": "0", "hash_probe": 1, "python": "test"}
    write(baseline / "protocol.json", {"model": "deepseek-flash", "corpus_id": "corpus",
          "runtime_identity": runtime, "parent_dataset": str(dev_dataset), "files": {}})
    candidate = tmp_path / "candidate"; candidate.mkdir()
    ablation = tmp_path / "ablation"; ablation.mkdir()
    write(candidate / "protocol.json", {"model": "deepseek-flash"})
    write(ablation / "protocol.json", {"model": "deepseek-flash"})
    evidence = tmp_path / "quality.json"; write(evidence, {"admitted": True})

    gate_dir = tmp_path / "gate"; gate_dir.mkdir(); gate_path = gate_dir / "implementation-gate.json"
    runs = {"baseline": baseline, "candidate": candidate, "ablation": ablation}
    gate = {"implementation_frozen": True, "holdout_opened": False,
            "selection_rule_applied_without_holdout": True, "model": "deepseek-flash",
            "development_reports": {"quality": {"path": str(evidence), "sha256": digest(evidence)}},
            "dev_runs": {name: {"path": str(path),
                                  "protocol_sha256": digest(path / "protocol.json")}
                         for name, path in runs.items()},
            "selected": {"source": "baseline", "source_run": str(baseline), "arm": "GN",
                         "method": "graph_first", "source_protocol_sha256": digest(baseline / "protocol.json"),
                         "source_arm_protocol_sha256": digest(baseline / "GN/protocol.json")},
            "holdout_runner_sha256": digest(Path(final_holdout.__file__))}
    write(gate_path, gate)

    output = tmp_path / "holdout-run"
    prepare(SimpleNamespace(run=output, gate=gate_path, dataset=dataset, kind="baseline"))
    protocol = json.loads((output / "protocol.json").read_text())
    assert protocol["holdout_unlocked"] is True
    assert protocol["planned_sessions"] == 6
    assert json.loads((output / "control/questions.json").read_text())[0]["id"] == "H1"
    assert json.loads((output / "GN/questions.json").read_text())[0]["id"] == "H1"
