"""Create a portable, non-destructive archive for the frozen candidate 010 baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from export_runtime_graph import export as export_runtime_graph


IMPLEMENTATION = (
    "candidate_graph_utils.py",
    "candidate_paths.py",
    "candidate_qa.py",
    "graphify_qa.py",
    "graphify_query_backend.py",
    "index_free_graph_evidence.py",
    "natural_index_free_leaderboard.py",
    "navigation_qa.py",
    "runner.py",
)

RESULTS = (
    "dev_v5_round_05_quality.json",
    "dev_v5_round_05_cost_and_grid.json",
    "dev_v5_round_05_error_analysis.json",
    "dev_v5_round_05_first_call_file_metrics.json",
    "dev_v5_round_05_first_call_file_report.md",
    "dev_v5_round_05_trace_retrieval_metrics.json",
    "dev_v5_round_05_trace_retrieval_report.md",
)

CONSTRUCTION_SNAPSHOT = (
    "candidate_graph.py",
    "candidate_graph_utils.py",
    "candidate_semantics.py",
    "candidate_semantic_completion.py",
    "candidate_case_aliases.py",
    "candidate_case_alias_completion.py",
)

CANONICAL_REFERENCES = (
    "self_graph_v2/candidates/005/graph.json",
    "self_graph_v2/candidates/005/validation.json",
    "self_graph_v2/builds/002/manifest.json",
    "self_graph_v2/construction_summary.json",
    "evaluations/dev_v5_round_05/protocol.json",
    "evaluations/dev_v5_round_05/principia-graph-validation.json",
)


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def record(path, base, role):
    return {
        "path": path.relative_to(base).as_posix(),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def freeze(chapter_root, source_root, destination):
    chapter_root = Path(chapter_root).resolve()
    source_root = Path(source_root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("archive destination already exists")
    destination.mkdir(parents=True)

    frozen_run = chapter_root / "evaluations/dev_v5_round_05"
    for name in IMPLEMENTATION:
        copy(frozen_run / name, destination / "implementation/frozen_candidate010" / name)
    copy(frozen_run / "protocol.json", destination / "protocol/evaluation_protocol.json")
    copy(
        chapter_root / "self_graph_v2/candidates/005/validation.json",
        destination / "graph/full_graph_validation.json",
    )
    for name in RESULTS:
        copy(chapter_root / "evaluations" / name, destination / "results" / name)
    for name in CONSTRUCTION_SNAPSHOT:
        copy(source_root / name, destination / "implementation/construction_snapshot" / name)

    runtime_path = destination / "graph/runtime_graph.json"
    export_runtime_graph(
        chapter_root / "self_graph_v2/candidates/005/graph.json",
        runtime_path,
        destination / "graph/runtime_graph.manifest.json",
    )

    local_files = sorted(
        path for path in destination.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "README.md"}
    )
    artifacts = [record(path, destination, "archived_copy") for path in local_files]
    for relative in CANONICAL_REFERENCES:
        path = chapter_root / relative
        artifacts.append({
            "path": "../../" + relative,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "role": "canonical_immutable_reference",
        })

    manifest = {
        "schema": "chapter2-candidate010-reuse-archive-v1",
        "baseline": "Principia candidate 010 / v5 development round 05",
        "frozen_graph_sha256": sha256(
            chapter_root / "self_graph_v2/candidates/005/graph.json"
        ),
        "nodes": 17376,
        "edges": 17144,
        "evaluation_status": (
            "development gate failed because paired family bootstrap CI lower "
            "bound versus strongest Graphify was 0; no holdout was opened"
        ),
        "archive_semantics": (
            "Frozen candidate 010 files are copied unchanged. The compact runtime "
            "graph and current construction snapshot are derived reuse aids and do "
            "not create candidate 011 or revise round 05."
        ),
        "artifacts": sorted(artifacts, key=lambda item: item["path"]),
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    manifest = freeze(args.chapter_root, args.source_root, args.destination)
    print(json.dumps({
        "destination": str(args.destination),
        "artifacts": len(manifest["artifacts"]),
        "graph_sha256": manifest["frozen_graph_sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
