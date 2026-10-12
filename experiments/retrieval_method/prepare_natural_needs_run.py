"""Prepare a compact, self-contained GN versus no-graph run from a frozen baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


GROUPS = {"control": ["no_graph"], "GN": ["graph_first"]}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def linktree(source, target):
    shutil.copytree(source, target, copy_function=os.link)


def prepare(source_run, dataset, output, replicates):
    if output.exists():
        raise FileExistsError(f"preserve existing run: {output}")
    source_protocol = read(source_run / "protocol.json")
    if source_protocol["model"] != "deepseek-flash":
        raise ValueError("source run is not exact deepseek-flash")
    dataset_protocol = read(dataset / "manifest.json")
    is_pilot = dataset_protocol.get("version") == "natural-user-needs-pilot-v1"
    for name, expected in dataset_protocol["artifacts"].items():
        if sha(dataset / name) != expected:
            raise ValueError(f"dataset artifact drift: {name}")
    output.mkdir(parents=True)
    # Freeze all Python dependencies used by the original runner.  Historical
    # adapters are harmless code copies; no legacy dataset is copied or read.
    for path in source_run.glob("*.py"):
        os.link(path, output / path.name)
    runner = (source_run / "runner.py").read_text()
    old = 'GROUPS = {**base.GROUPS, "GN": ["graph_first"], "GH": ["graph_first"],\n          "GH_evidence": ["graph_first"]}'
    new = 'GROUPS = {"control": ["no_graph"], "GN": ["graph_first"]}'
    if runner.count(old) != 1:
        raise ValueError("unexpected frozen runner GROUPS declaration")
    (output / "runner.py").unlink()
    (output / "runner.py").write_text(runner.replace(old, new))
    questions = read(dataset / "dev.questions.json")
    annotations = read(dataset / "dev.annotations.json")
    if {q["item_id"] for q in questions} != {a["id"] for a in annotations}:
        raise ValueError("question/annotation identity mismatch")
    for arm, methods in GROUPS.items():
        source_arm, target = source_run / arm, output / arm
        target.mkdir()
        for name in ("skill",):
            linktree(source_arm / name, target / name)
        for name in ("corpus-manifest.json", "all-files.json", "path-map.json"):
            os.link(source_arm / name, target / name)
        if arm == "GN":
            linktree(source_arm / "graphify-out", target / "graphify-out")
        write(target / "questions.json", questions)
        (target / "evaluation_only").mkdir()
        shutil.copy2(dataset / "dev.annotations.json", target / "evaluation_only/annotations.json")
        shutil.copy2(dataset / "scoring-rules.json", target / "evaluation_only/scoring-rules.json")
        source_arm_protocol = read(source_arm / "protocol.json")
        source_arm_protocol.update({
            "arm": arm, "methods": methods, "replicates": replicates,
            "dataset_manifest_sha256": sha(dataset / "manifest.json"),
            "question_scope": "natural user needs; concrete cases and targets evaluation-only",
            "quality_status": "unscored until blinded source-grounded review",
        })
        source_arm_protocol["files"] = {
            p.relative_to(target).as_posix(): sha(p) for p in sorted(target.rglob("*"))
            if p.is_file() and p != target / "protocol.json"
        }
        write(target / "protocol.json", source_arm_protocol)
    protocol = dict(source_protocol)
    protocol.update({
        "schema": "natural-user-needs-gn-control-pilot-v1" if is_pilot else "natural-user-needs-gn-control-full-v1", "groups": GROUPS,
        "replicates": replicates, "parent_dataset": str(dataset),
        "dataset_manifest_sha256": sha(dataset / "manifest.json"),
        "planned_sessions": len(questions) * replicates * 2,
        "scope_revision": f"{len(questions)} natural user needs, one original wording each; cases, solver names, files and gold hidden from answer generation.",
        "pre_run_revision": "Two arms only: frozen GN graph_first versus matched control no_graph; exact prior runtime and budgets.",
        "holdout_unlocked": False, "quality_reviewed": False,
        "expansion_gate": (
            "Full natural-needs iteration runs only if this frozen pilot shows GN directional improvement over control."
            if is_pilot else
            "Passed before this run was frozen: pilot GN strict success 27.8% versus no-graph 5.6%."
        ),
    })
    protocol["files"] = {
        p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*"))
        if p.is_file() and p != output / "protocol.json"
    }
    write(output / "protocol.json", protocol)
    print(json.dumps({"output": str(output), "questions": len(questions),
                      "planned_sessions": protocol["planned_sessions"],
                      "protocol_sha256": sha(output / "protocol.json")}, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-run", type=Path, required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--replicates", type=int, default=3)
    a = p.parse_args()
    if a.replicates != 3:
        raise ValueError("natural-needs comparison requires three repeats")
    prepare(a.source_run.resolve(), a.dataset.resolve(), a.output.resolve(), a.replicates)


if __name__ == "__main__":
    main()
