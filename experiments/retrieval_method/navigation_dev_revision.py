"""看过开发结果后的问题范围修订；不解析留出内容，不修改gold或重算旧分数。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def blob(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def verify_files(root, files):
    root = root.resolve()
    for name, expected in files.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("frozen parent artifact mismatch: " + name)


def transform(questions, revision):
    if revision.get("observed_development_results") is not True or not revision.get("version"):
        raise ValueError("post-observation dev revision must explicitly record observed results and version")
    if not revision.get("reason") or not revision.get("patches"):
        raise ValueError("revision reason and patches required")
    known = {q["id"]: q for q in questions}
    if len(known) != len(questions) or not set(revision["patches"]) <= set(known):
        raise ValueError("duplicate or unknown dev question")
    revised = []
    for row in questions:
        patch = revision["patches"].get(row["id"])
        if patch is None:
            revised.append(dict(row))
            continue
        if set(patch) != {"before", "after", "reason"} or patch["before"] != row["question"]:
            raise ValueError("revision must bind exact previous question and cannot change other fields")
        if not all(isinstance(patch[k], str) and patch[k].strip() for k in patch):
            raise ValueError("empty question or reason")
        if patch["after"] == patch["before"]:
            raise ValueError("no-op patch")
        revised.append({**row, "question": patch["after"]})
    if len({q["question"] for q in revised}) != len(revised):
        raise ValueError("duplicate revised question")
    return revised


def build(parent, baseline, revision_path, output):
    if output.exists():
        raise FileExistsError("Preserve existing dataset directory; use a new version")
    parent = parent.resolve()
    baseline = baseline.resolve()
    parent_raw = (parent / "manifest.json").read_bytes()
    parent_manifest = json.loads(parent_raw)
    # Hash checks may read raw holdout bytes; their contents are never parsed or copied.
    verify_files(parent, parent_manifest["artifacts"])
    protocol_raw = (baseline / "protocol.json").read_bytes()
    protocol = json.loads(protocol_raw)
    verify_files(baseline, protocol["files"])
    revision_raw = revision_path.read_bytes()
    revision = json.loads(revision_raw)
    observed_name = revision["observed_metrics"]["file"]
    verify_files(baseline, {observed_name: revision["observed_metrics"]["sha256"]})
    questions = json.loads((parent / "dev.questions.json").read_bytes())
    if questions != json.loads((baseline / "control/questions.json").read_bytes()):
        raise ValueError("baseline questions differ from declared parent")
    annotations_raw = (parent / "dev.annotations.json").read_bytes()
    rules_raw = (parent / "scoring-rules.json").read_bytes()
    if annotations_raw != (baseline / "control/evaluation_only/annotations.json").read_bytes():
        raise ValueError("baseline gold differs from declared parent")
    if rules_raw != (baseline / "control/evaluation_only/scoring-rules.json").read_bytes():
        raise ValueError("baseline scoring differs from declared parent")
    annotations = json.loads(annotations_raw)
    if any(a["split"] != "dev" for a in annotations):
        raise ValueError("dev-only revision cannot contain holdout annotations")
    revised = transform(questions, revision)
    if {q["item_id"] for q in revised} != {a["id"] for a in annotations}:
        raise ValueError("question/annotation identity mismatch")
    corpus_raw = (baseline / "control/corpus-manifest.json").read_bytes()
    corpus = json.loads(corpus_raw)
    files = {"dev.questions.json": blob(revised), "dev.annotations.json": annotations_raw,
             "scoring-rules.json": rules_raw, "corpus-manifest.json": corpus_raw, "revision.json": revision_raw}
    manifest = {
        "version": revision["version"], "split": "dev-only", "observed_development_results": True,
        "parent_dataset": str(parent), "parent_manifest_sha256": sha(parent_raw),
        "parent_baseline": str(baseline), "parent_baseline_protocol_sha256": sha(protocol_raw),
        "observed_metrics": revision["observed_metrics"],
        "compiler_sha256": sha(Path(__file__).read_bytes()), "changed_questions": sorted(revision["patches"]),
        "unchanged_gold_sha256": sha(annotations_raw), "unchanged_scoring_sha256": sha(rules_raw),
        "counts": {"dev": {"items": len(annotations), "questions": len(revised),
                  "categories": dict(Counter(a["category"] for a in annotations))}},
        "corpus_id": protocol["corpus_id"], "source_files": len(corpus),
        "corpus_scope": "Exactly the frozen common raw-text corpus from the reviewed baseline; not the older 688-file scope.",
        "parent_holdout_artifact_sha256": {n: h for n, h in parent_manifest["artifacts"].items() if n.startswith("holdout.")},
        "holdout_policy": "Remain frozen at external parent; hash-verified only, not parsed, copied, revised or evaluated here.",
        "limits": ["Post-development-result question revision, not an unseen benchmark.",
                   "Old scores and answers remain tied to their old questions; all methods require new matched runs.",
                   "Question-only clarification does not establish new independent holdout generalization."],
        "artifacts": {n: sha(raw) for n, raw in files.items()},
    }
    # All identities and revision constraints pass before creating any output artifact.
    output.mkdir(parents=True)
    for name, raw in files.items():
        (output / name).write_bytes(raw)
    (output / "manifest.json").write_bytes(blob(manifest))
    print(json.dumps({"output": str(output), "version": manifest["version"], "questions": len(revised),
                      "changed": len(revision["patches"]), "source_files": len(corpus)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.parent, args.baseline, args.revision, args.output)
