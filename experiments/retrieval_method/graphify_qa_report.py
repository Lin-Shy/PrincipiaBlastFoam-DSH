"""汇总冻结五臂运行：调用冻结计量/评分函数，不替代逐项来源审阅。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import statistics
import time


def report(run, output, reviews_root=None):
    spec = importlib.util.spec_from_file_location("frozen_graphify_metrics", run / "navigation_metrics.py")
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)
    protocol = metrics.read(run / "protocol.json")
    for path, expected in protocol["files"].items():
        if metrics.sha((run/path).read_bytes()) != expected:
            raise ValueError("Frozen experiment changed: " + path)
    rows, overhead = [], {}
    for group in protocol["groups"]:
        root = run / group
        annotations = {a["id"]: a for a in metrics.read(root/"evaluation_only/annotations.json")}
        scoring = metrics.read(root/"evaluation_only/scoring-rules.json")
        reviews = {}
        if reviews_root and (reviews_root / (group + ".json")).exists():
            reviews = {r["session"]: r for r in metrics.read(reviews_root/(group + ".json"))}
        raw_loads = [metrics.read(p) for p in sorted(root.glob("raw-corpus-load-*.json"))]
        non_replay = [r for r in raw_loads if r.get("replay") is False]
        overhead[group] = {"raw_loads": non_replay,
            "unclassified_raw_loads": sum("replay" not in r for r in raw_loads),
            "raw_load_seconds": sum(r["seconds"] for r in non_replay),
            "scope": "Shared arm corpus cache loads, excluded from individual session timers; count once for this archive, not once per question. Graph cold init is already inside affected tool latency."}
        for folder in sorted((root/"sessions").glob("*")):
            if not folder.is_dir():
                continue
            annotation = annotations[folder.name.split("-p")[0]]
            row = metrics.session_metrics(folder, annotation)
            if folder.name in reviews:
                metrics.merge_review(row, reviews[folder.name], annotation, scoring,
                                     metrics.read(folder/"result.json")["seen_lines"])
            row.update(group=group, arm=group+"/"+row["method"])
            rows.append(row)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["arm"], row["category"]].append(row)
        grouped[row["arm"], "overall"].append(row)
    summary = []
    numeric = ("tool_calls", "graph_queries", "file_search_calls", "catalog_calls", "source_read_calls",
               "repeated_search_calls", "failed_tool_calls", "returned_context_characters",
               "reported_total_model_tokens", "retrieval_seconds", "session_seconds", "transport_failures",
               "unknown_usage_attempts", "unknown_api_duration_attempts", "unknown_session_duration_invocations")
    for (arm, category), selected in sorted(grouped.items()):
        reviewed = [r for r in selected if r["quality_reviewed"]]
        content, attempted = Counter(), Counter()
        for row in selected:
            content.update(row["internal_content"])
            attempted.update(row["attempted_request_content"])
        summary.append({"arm": arm, "category": category, "sessions": len(selected),
            "complete_answers": sum(r["status"] == "complete" for r in selected),
            "reviewed": len(reviewed), "successes": sum(r["qa_success"] for r in reviewed) if reviewed else None,
            "sums": {k: sum(r[k] for r in selected) for k in numeric},
            "means": {k: statistics.mean(r[k] for r in selected) for k in numeric},
            "quality_means_reviewed_only": {k: statistics.mean(r[k] for r in reviewed if r.get(k) is not None)
                if any(r.get(k) is not None for r in reviewed) else None for k in scoring["quality"]},
            "internal_content_sums_overlapping_counters_not_additive": dict(content),
            "attempted_request_content_sums": dict(attempted)})
    invocations = [metrics.read(p) for p in sorted((run/"invocations").glob("*.json"))]
    invocations = [r for r in invocations if r["command"] == "run"]
    pairs = defaultdict(set)
    for row in rows:
        if row["status"] == "complete":
            pairs[row["session"].split("--")[0]].add(row["arm"])
    all_arms = {g+"/"+m for g, methods in protocol["groups"].items() for m in methods}
    result = {"protocol_sha256": metrics.sha((run/"protocol.json").read_bytes()),
        "reporter_sha256": metrics.sha(Path(__file__).read_bytes()), "sessions": rows, "summary": summary,
        "shared_initialization": overhead, "invocations": invocations,
        "complete_five_arm_questions": sorted(q for q, arms in pairs.items() if arms == all_arms),
        "quality_gate": "unreviewed_or_partial" if any(not r["quality_reviewed"] for r in rows) else "reviewed",
        "limits": ["Reported tokens are a lower bound whenever unknown_usage_attempts is nonzero.",
            "Internal character projections overlap; do not add them or equate them to LLM tokens.",
            "Evidence-span coverage is not semantic answer correctness.",
            "No_graph is shared once, not duplicated in archive totals.",
            "Session and API time sums overlap under parallel execution; root invocation wall is separate.",
            "Root elapsed excludes corpus preparation, verification and reporting; engine initialization separately recorded.",
            "Development one-replicate data cannot prove holdout generalization or stable cost reduction."]}
    if output.exists():
        raise FileExistsError("Preserve prior report")
    metrics.save(output, result)
    print(json.dumps({"output": str(output), "sessions": len(rows),
        "complete_five_arm_questions": result["complete_five_arm_questions"],
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "reported_tokens": sum(r["reported_total_model_tokens"] for r in rows),
        "unknown_usage_attempts": sum(r["unknown_usage_attempts"] for r in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviews-root", type=Path)
    args = parser.parse_args()
    report(args.run, args.output or args.run/("metrics-"+str(time.time_ns())+".json"), args.reviews_root)
