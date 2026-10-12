"""汇总已完成的显式质量审阅；不生成或更改答案评分，不调用模型。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics


DIMENSIONS = (
    "concept_accuracy", "case_accuracy", "file_dictionary_accuracy", "manual_accuracy",
    "cross_source_completeness", "required_evidence_recall", "citation_accuracy",
    "evidence_status_accuracy", "ambiguity_accuracy", "answer_accuracy", "qa_success",
    "first_answer_success",
)
COSTS = (
    "tool_calls", "graph_queries", "file_search_calls", "source_read_calls", "catalog_calls",
    "repeated_search_calls", "failed_tool_calls", "reported_total_model_tokens", "answer_tokens",
    "unknown_usage_attempts", "transport_attempts", "transport_retries", "returned_context_characters",
    "retrieval_seconds", "session_seconds",
)


def average(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def key(row):
    question, _, replicate = row["session"].split("--")
    return question + "--" + replicate


def totals(rows):
    return {name: sum(r[name] for r in rows) for name in COSTS}


def analyze(report):
    rows = report["sessions"]
    if not rows or report["quality_gate"] != "reviewed" or any(not r["quality_reviewed"] for r in rows):
        raise ValueError("requires completed explicit review; do not silently drop unreviewed rows")
    grouped = defaultdict(dict)
    for row in rows:
        if key(row) in grouped[row["arm"]]:
            raise ValueError("duplicate arm/question/replicate")
        if not row.get("review", {}).get("gold_points"):
            raise ValueError("explicit point review missing")
        grouped[row["arm"]][key(row)] = row
    if "control/no_graph" not in grouped:
        raise ValueError("shared no_graph control missing")
    control = grouped["control/no_graph"]
    if any(set(group) != set(control) for group in grouped.values()):
        raise ValueError("paired comparison requires the same question/replicate set")
    result = {"protocol_sha256": report["protocol_sha256"], "sessions": len(rows), "arms": {}}
    for arm, indexed in sorted(grouped.items()):
        selected = list(indexed.values())
        categories = sorted({r["category"] for r in selected})
        quality = {}
        for category in [*categories, "overall"]:
            subset = selected if category == "overall" else [r for r in selected if r["category"] == category]
            quality[category] = {name: {"n_applicable": sum(r[name] is not None for r in subset),
                "mean": average(r[name] for r in subset)} for name in DIMENSIONS}
        macro = {name: average(quality[c][name]["mean"] for c in categories) for name in DIMENSIONS}
        families = defaultdict(list)
        for r in selected:
            families[(r["item_id"], r["session"].split("--")[-1])].append(r)
        rewrite = {"family_replicates": len(families), "both_or_all_success": [], "mixed_success": [],
                   "all_failure": [], "insufficient_paraphrases": []}
        for (item, repeat), variants in sorted(families.items()):
            label = item + "--" + repeat
            successes = sum(r["qa_success"] for r in variants)
            bucket = ("insufficient_paraphrases" if len(variants) < 2 else
                      "both_or_all_success" if successes == len(variants) else
                      "all_failure" if successes == 0 else "mixed_success")
            rewrite[bucket].append(label)
        full_points = [key(r) for r in selected if all(p["score"] == 2 for p in r["review"]["gold_points"])]
        citation_only = [key(r) for r in selected if key(r) in full_points
            and not r["review"]["extra_errors"] and r["citation_accuracy"] < 1
            and all(r[d] in (None, 1) for d in DIMENSIONS[:9] if d != "citation_accuracy")]
        failures = {d: [key(r) for r in selected if r[d] is not None and r[d] < 1] for d in DIMENSIONS[:9]}
        common = sorted(k for k, r in indexed.items() if r["qa_success"] and control[k]["qa_success"])
        result["arms"][arm] = {
            "sessions": len(selected), "quality": quality, "equal_category_macro": macro,
            "strict_successes": [key(r) for r in selected if r["qa_success"]],
            "all_gold_points_full": full_points, "citation_only_failure": citation_only,
            "nonexclusive_dimension_failures": failures, "rewrite_consistency": rewrite,
            "all_session_costs": totals(selected),
            "common_success_with_control": {"questions": common,
                "arm_costs": totals([indexed[k] for k in common]),
                "control_costs": totals([control[k] for k in common]),
                "interpretation": "Post-outcome diagnostic subset, not an unbiased quality/cost comparison."},
        }
    result["limits"] = [
        "All original scores are reused, not rescored by this diagnostic summary.",
        "Failure lists overlap and indicate failed quality gates, not proven causes or causal attribution.",
        "Citation-only means other reviewed gates pass; it does not predict success after a formatting intervention.",
        "Paraphrases are correlated; all-failure agreement is not useful success stability; repeats remain distinct.",
        "Unknown-usage failures are not zero; reported-token differences are not true-total cost differences.",
        "Full cost detail and overlapping internal counters remain in the referenced source metrics.",
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve previous analysis")
    raw = args.metrics.read_bytes()
    result = analyze(json.loads(raw))
    result["source_metrics"] = str(args.metrics.resolve())
    result["source_metrics_sha256"] = hashlib.sha256(raw).hexdigest()
    result["analyzer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "sessions": result["sessions"]}))


if __name__ == "__main__":
    main()
