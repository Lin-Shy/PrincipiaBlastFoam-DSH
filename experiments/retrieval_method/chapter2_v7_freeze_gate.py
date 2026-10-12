"""在查看新版留出结果前冻结实现、开发结果与全部评测输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import time

RUNTIME = ("navigation_qa.py", "graphify_query_backend.py", "graphify_qa.py", "candidate_qa.py",
           "candidate_graph_utils.py", "candidate_paths.py", "index_free_graph_evidence.py",
           "candidate_hybrid.py", "vector_retrieval_qa.py")
ARMS = ("control", "native", "text_adapter", "principia_index_free", "vector_e5_dense")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--dev-run", type=Path, required=True)
    p.add_argument("--dev-reviews", type=Path, required=True)
    p.add_argument("--dev-quality", type=Path, required=True)
    p.add_argument("--timing-code", type=Path, required=True)
    p.add_argument("--quality-code", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("freeze gate exists")
    dataset_manifest = load(a.dataset / "manifest.json")
    run_protocol = load(a.dev_run / "protocol.json")
    if dataset_manifest["schema"] != "natural-navigation-qa-v7r1-20-80" or run_protocol["split"] != "dev":
        raise ValueError("wrong dataset/run")
    if run_protocol["dataset_manifest_sha256"] != sha(a.dataset / "manifest.json"):
        raise ValueError("dev dataset mismatch")
    for name, expected in run_protocol["files"].items():
        if sha(a.dev_run / name) != expected:
            raise ValueError("dev frozen input drift: " + name)
    quality = load(a.dev_quality)
    if quality["run_protocol_sha256"] != sha(a.dev_run / "protocol.json") or quality["dataset_manifest_sha256"] != sha(a.dataset / "manifest.json"):
        raise ValueError("quality provenance mismatch")
    for arm in ARMS:
        if quality["methods"][arm]["compiled_reviews"] != 60:
            raise ValueError("incomplete dev review grid: " + arm)
    runtime_hashes = {name: sha(a.dev_run / name) for name in RUNTIME}
    arm_protocol_hashes = {arm: sha(a.dev_run / arm / "protocol.json") for arm in ARMS}
    gate = {"schema": "chapter2-v7-holdout-freeze-gate-v1", "created_unix_ns": time.time_ns(),
            "implementation_frozen": True, "dataset_manifest_sha256": sha(a.dataset / "manifest.json"),
            "dev_runs": {"path": str(a.dev_run), "protocol_sha256": sha(a.dev_run / "protocol.json"),
                         "completed_sessions": {arm: quality["methods"][arm]["complete_answers"] for arm in ARMS}},
            "dev_reviews": {"path": str(a.dev_reviews), "protocol_sha256": sha(a.dev_reviews / "protocol.json"),
                            "quality_sha256": sha(a.dev_quality)},
            "runtime_files_sha256": runtime_hashes, "arm_protocol_sha256": arm_protocol_hashes,
            "graph_sha256": sha(a.dev_run / "principia-graph.json"),
            "vector_index_manifest_sha256": sha(a.dev_run / "vector-index/manifest.json"),
            "timing_code_sha256": sha(a.timing_code), "quality_code_sha256": sha(a.quality_code),
            "holdout_policy": "one final workflow after this gate; results do not change this version",
            "legacy_v5_eight_point_gate": "not a stop condition"}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"frozen": True, "dataset_manifest_sha256": gate["dataset_manifest_sha256"]}))


if __name__ == "__main__":
    main()
