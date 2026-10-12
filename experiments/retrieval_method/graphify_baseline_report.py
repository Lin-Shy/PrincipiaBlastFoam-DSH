"""冻结 Graphify 产物身份、覆盖清单与全阶段 HTTP 成本，不给问答打分。"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import subprocess
import sys
import time

from graphify_baseline import now, sha, verify_corpus, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--variant", choices=["native", "text_adapter"], required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    corpus, manifest, mapping = verify_corpus(archive, args.variant)
    inverse = {v: k for k, v in mapping.items()}
    run = archive / args.variant
    out = run / "graphify-out"
    final = run / "baseline_summary.json"
    if final.exists():
        raise FileExistsError("Baseline summary already frozen")
    paths = sorted((run / "attempts").glob("*/run.json")) + [run / "presentation/run.json"]
    stage_runs = [json.loads(p.read_text()) for p in paths]
    if any(item["state"] != "completed" for item in stage_runs):
        raise ValueError("Construction stage still running or failed")
    graph = json.loads((out / "graph.json").read_text())
    nodes, edges = graph["nodes"], graph.get("links", graph.get("edges", []))
    ids = {n["id"] for n in nodes}
    dangling = [e for e in edges if e["source"] not in ids or e["target"] not in ids]
    if len(ids) != len(nodes) or dangling:
        raise ValueError("Duplicate nodes or dangling graph edges")

    def original_source(item):
        source = item.get("source_file")
        if not source:
            return None
        if Path(source).is_absolute():
            try:
                source = Path(source).relative_to(corpus).as_posix()
            except ValueError:
                return None
        return inverse.get(source)

    def category(item):
        source = original_source(item)
        return source.split("/")[0] if source else "unresolved"

    by_id = {n["id"]: n for n in nodes}
    represented = {original_source(n) for n in nodes} - {None}
    detected_file = "native_detection.json" if args.variant == "native" else "text_adapter_detection.json"
    detection = json.loads((archive / detected_file).read_text())
    recognized = {inverse[Path(p).relative_to(corpus).as_posix()]
                  for group in detection["files"].values() for p in group}
    source_rows = [{**row, "graph_input_path": mapping[row["path"]],
                    "recognized": row["path"] in recognized,
                    "has_node_primary_provenance": row["path"] in represented}
                   for row in manifest["files"]]
    write_json(run / "source_coverage.json", source_rows)
    http_files = sorted((run / "attempts").glob("*/http/*.json")) + sorted((run / "presentation/http").glob("*.json"))
    requests = [json.loads(p.read_text()) for p in http_files]
    usage = collections.Counter()
    nested_usage = collections.Counter()
    for item in requests:
        for key, value in (item.get("usage") or {}).items():
            if isinstance(value, (int, float)):
                usage[key] += value
            elif isinstance(value, dict):
                for subkey, number in value.items():
                    if isinstance(number, (int, float)):
                        nested_usage[key + "." + subkey] += number
    unknown = [str(path.relative_to(run)) for path, item in zip(http_files, requests)
               if not item.get("usage")]
    over_cap = [str(path.relative_to(run)) for path, item in zip(http_files, requests)
                if (item.get("usage") or {}).get("completion_tokens", 0)
                > (item.get("request") or {}).get("max_completion_tokens", float("inf"))]
    image_payloads = sum(
        part.get("type") in {"image_url", "input_image"}
        for request in requests for message in request.get("request", {}).get("messages", [])
        if isinstance(message.get("content"), list) for part in message["content"] if isinstance(part, dict)
    )
    crossing = [e for e in edges if {category(by_id[e["source"]]), category(by_id[e["target"]])}
                == {"manual", "tutorials"}]
    write_json(run / "cross_source_edges.json", crossing)
    missing = [row["path"] for row in manifest["files"] if row["path"] not in represented]
    drift = [row["path"] for row in manifest["files"]
             if not Path(row["original_path"]).is_file()
             or sha(Path(row["original_path"]).read_bytes()) != row["sha256"]]
    summary = {
        "created_at": now(), "variant": args.variant,
        "status": "construction_outputs_frozen_not_QA_evaluated",
        "corpus_id": manifest["corpus_id"],
        "upstream_identity": json.loads((archive / "upstream_identity.json").read_text())["implementation_identity"],
        "counts": {"input_files": len(manifest["files"]), "recognized_files": len(recognized),
                   "primary_provenance_files": len(represented), "nodes": len(nodes), "edges": len(edges),
                   "hyperedges": len(graph.get("hyperedges", [])),
                   "communities": len({n.get("community") for n in nodes}),
                   "cross_source_edges_by_endpoint_primary_source": len(crossing),
                   "nodes_by_source": dict(collections.Counter(category(n) for n in nodes)),
                   "edges_by_declared_confidence": dict(collections.Counter(e.get("confidence", "missing") for e in edges)),
                   "nodes_with_nonempty_source_location": sum(bool(n.get("source_location")) for n in nodes),
                   "nodes_with_unresolved_primary_source": sum(original_source(n) is None for n in nodes),
                   "dangling_edges": len(dangling)},
        "original_source_drift_since_freeze": drift,
        "files_without_node_primary_provenance": missing,
        "recognized_without_node_primary_provenance": sorted(recognized - represented),
        "costs": {"stages": stage_runs, "elapsed_seconds_sum": sum(x["elapsed_seconds"] for x in stage_runs),
                  "http_attempts": len(requests), "states": dict(collections.Counter(x["state"] for x in requests)),
                  "reported_usage_sum": dict(usage), "reported_nested_usage_sum": dict(nested_usage),
                  "unknown_usage_attempts": unknown, "usage_is_lower_bound": bool(unknown),
                  "response_completion_tokens_exceed_request_max_completion_tokens": over_cap,
                  "image_payloads_sent": image_payloads,
                  "request_bytes_all_attempts": sum(x["request_bytes"] for x in requests),
                  "notes": ["Construction + community labeling, not answer-time cost.",
                            "Do not add reasoning tokens a second time; they are part of completion_tokens.",
                            "Graphify's report may show labeling-stage tokens only; this ledger sums both stages.",
                            "No monetary charge claimed; native cost estimator is not model-specific billing.",
                            "Path.read_* counters in stage costs are incomplete I/O equivalents, not all reads."]},
        "limitations": ["EXTRACTED/INFERRED are Graphify labels, not independent factual verification.",
                        "Having a source node does not mean all its facts were extracted.",
                        "Source location presence does not establish the citation is correct.",
                        "No image payloads means image nodes cannot be treated as pixel-grounded extraction.",
                        "Native built_at_commit refers to input/ancestor Git discovery, not Graphify version or frozen corpus identity.",
                        "Construction counts and query smoke checks are not retrieval QA accuracy or savings."],
    }
    # Use official CLI only. These developer queries are smoke checks, not gold
    # questions, scored evaluation or new construction inputs.
    smoke = []
    for index, query in enumerate(("JWL 状态方程 教程配置", "movingCone dynamicMeshDict", "自适应网格细化 AMR 配置条件"), 1):
        command = [sys.executable, "-m", "graphify", "query", query,
                   "--graph", str(out / "graph.json"), "--budget", "1500"]
        started = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        row = {"query": query, "argv": command, "exit_code": result.returncode,
               "elapsed_seconds": time.perf_counter() - started,
               "stdout": result.stdout, "stderr": result.stderr,
               "stdout_chars": len(result.stdout), "scored_QA": False}
        write_json(run / "query_smoke" / f"{index:02d}.json", row)
        smoke.append({k: v for k, v in row.items() if k not in {"stdout", "stderr", "argv"}})
    summary["query_smoke"] = smoke
    artifacts = {}
    for name in ("graph.json", "GRAPH_REPORT.md", "graph.html", ".graphify_analysis.json", ".graphify_labels.json", "manifest.json"):
        path = out / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing completed output: {name}")
        artifacts[name] = {"sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
    summary["artifacts"] = artifacts
    summary["baseline_id"] = sha(json.dumps({"corpus": manifest["corpus_id"],
        "implementation": summary["upstream_identity"], "variant": args.variant,
        "graph": artifacts["graph.json"]["sha256"]}, sort_keys=True).encode())
    write_json(final, summary)
    print(json.dumps({"baseline_id": summary["baseline_id"], "counts": summary["counts"],
                      "tokens": dict(usage), "smoke": smoke}, ensure_ascii=False))


if __name__ == "__main__":
    main()
