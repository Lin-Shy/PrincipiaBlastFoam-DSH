"""Summarize the frozen independent Flash construction chain and its exact API ledger."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ledger(stages):
    usage, models, statuses = Counter(), Counter(), Counter()
    request_files = 0
    for stage in stages:
        for path in stage.glob("sessions/**/*.json"):
            value = read(path)
            if "request_sha256" not in value:
                continue
            request_files += 1
            response = value.get("raw_response", {})
            if response:
                models[response.get("model", "missing")] += 1
            for event in value.get("events", []):
                statuses[event.get("status", "missing")] += 1
            reported = response.get("usage", {}) if isinstance(response, dict) else {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                if key in reported:
                    usage[key] += reported[key]
    return {"request_files": request_files, "provider_models": dict(models),
            "attempt_statuses": dict(statuses), "reported_usage": dict(usage)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args();root = args.root.resolve()
    structure = root / "builds/002";relations = root / "relations/002"
    stages = [root / f"semantics/{number:03}" for number in (4, 5, 6)]
    candidate = root / "candidates/002";semantic = read(stages[-1] / "layer.json")
    manifest, validation = read(structure / "manifest.json"), read(candidate / "validation.json")
    calls = ledger(stages)
    if set(calls["provider_models"]) != {"deepseek-flash"}:
        raise ValueError("semantic construction contains a non-Flash provider model")
    if manifest.get("parent_variant") != "none" or not manifest.get("independent_of_graphify_graph"):
        raise ValueError("self graph still depends on Graphify graph")
    if not semantic["complete"] or validation["status"] != "passed":
        raise ValueError("construction validation incomplete")
    result = {"schema": "principia-index-free-construction-summary-v1",
        "corpus_id": manifest["corpus_id"], "model": "deepseek-flash",
        "independent_of_graphify_graph": True, "external_retrieval_index": False,
        "forbidden_components_absent": ["E5", "BM25", "vector store", "inverted index", "passage embeddings"],
        "structure": {"path": str(structure), "manifest_sha256": sha(structure / "manifest.json"),
                      "nodes": manifest["variants"]["GH"]["nodes"], "edges": manifest["variants"]["GH"]["edges"],
                      "model_calls": 0},
        "deterministic_relations": {"path": str(relations), "manifest_sha256": sha(relations / "manifest.json"),
                                    **read(relations / "stats.json")},
        "semantic_stages": [{"path": str(stage), "protocol_sha256": sha(stage / "protocol.json"),
                             "layer_sha256": sha(stage / "layer.json")} for stage in stages],
        "semantic": {"complete": True, "files": len(semantic["coverage"]),
                     "definitions": semantic["definitions"], "assertions": semantic["assertions"],
                     "rejected": semantic["rejected"], "api": calls},
        "final_graph": {"path": str(candidate / "graph.json"), "sha256": sha(candidate / "graph.json"),
                        "validation_sha256": sha(candidate / "validation.json"), "nodes": validation["nodes"],
                        "edges": validation["edges"], "bilateral_relation_counts": validation["bilateral_relation_counts"]},
        "question_or_gold_used_in_construction": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"model": result["model"], "nodes": validation["nodes"], "edges": validation["edges"],
                      "semantic_requests": calls["request_files"], "tokens": calls["reported_usage"].get("total_tokens")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
