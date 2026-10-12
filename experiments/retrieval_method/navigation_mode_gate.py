"""Compile the frozen post-hoc navigation-mode replacement decision."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics

import leaderboard_audit as audit


EVIDENCE_ARM = "candidate010_evidence"
NAVIGATION_ARM = "candidate010_navigation"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metric(arm, name):
    return arm["metrics"][name]["macro_over_applicable_categories"]


def family_success(arm):
    values = defaultdict(list)
    for session in arm["sessions"]:
        values[session["family"]].append(int(session["quality"]["qa_success"]))
    return {family: statistics.mean(rows) for family, rows in sorted(values.items())}


def trace_stats(run, arm_name, navigation_expected=False):
    rows = []
    action_counts = Counter()
    navigation_leaks = []
    invalid_navigation_payloads = []
    for path in sorted((run / arm_name / "sessions").glob("*/result.json")):
        result = audit.read(path)
        actions = [event.get("action", {}).get("action") for event in result["events"]]
        action_counts.update(action for action in actions if isinstance(action, str))
        locates = [
            event for event in result["events"]
            if event.get("action", {}).get("action") == "locate"
        ]
        for event in locates if navigation_expected else []:
            payload = event.get("result", {})
            if "evidence" in payload or "items" in payload or "locations" in payload:
                navigation_leaks.append(result["id"])
            if payload.get("status") == "ok" and not payload.get("navigation_only"):
                invalid_navigation_payloads.append(result["id"])
        rows.append({
            "question_id": result["id"],
            "status": result["status"],
            "decisions": len(result["events"]),
            "locates": len(locates),
            "first_locate_characters": (
                locates[0].get("returned_characters") if locates else None
            ),
            "all_locate_characters": sum(
                event.get("returned_characters", 0) for event in locates
            ),
            "total_returned_characters": result["returned_characters"],
            "read_sources": "read_sources" in actions,
            "seen_files": len(result["seen_lines"]),
            "seen_lines": sum(len(lines) for lines in result["seen_lines"].values()),
            "tool_seconds": sum(
                event.get("accounting", {}).get("seconds", 0)
                for event in result["events"]
                if isinstance(event.get("accounting", {}).get("seconds", 0), (int, float))
            ),
            "locate_seconds": sum(
                event.get("accounting", {}).get("seconds", 0)
                for event in locates
                if isinstance(event.get("accounting", {}).get("seconds", 0), (int, float))
            ),
        })
    return {
        "sessions": len(rows),
        "statuses": dict(Counter(row["status"] for row in rows)),
        "action_counts": dict(action_counts),
        "mean_decisions": statistics.mean(row["decisions"] for row in rows),
        "read_sources_sessions": sum(row["read_sources"] for row in rows),
        "read_sources_rate": statistics.mean(row["read_sources"] for row in rows),
        "first_locate_sessions": sum(
            row["first_locate_characters"] is not None for row in rows
        ),
        "first_locate_mean_characters": statistics.mean(
            row["first_locate_characters"]
            for row in rows if row["first_locate_characters"] is not None
        ),
        "all_locate_mean_characters": statistics.mean(
            row["all_locate_characters"] for row in rows
        ),
        "total_returned_mean_characters": statistics.mean(
            row["total_returned_characters"] for row in rows
        ),
        "mean_seen_files": statistics.mean(row["seen_files"] for row in rows),
        "mean_seen_lines": statistics.mean(row["seen_lines"] for row in rows),
        "mean_tool_seconds": statistics.mean(row["tool_seconds"] for row in rows),
        "mean_locate_seconds": statistics.mean(row["locate_seconds"] for row in rows),
        "navigation_original_text_leaks": sorted(set(navigation_leaks)),
        "invalid_successful_navigation_payloads": sorted(
            set(invalid_navigation_payloads)
        ),
    }


def compile_gate(run, quality_path, cost_path):
    protocol = audit.verify(run)
    quality = audit.read(quality_path)
    cost = audit.read(cost_path)
    if not quality.get("all_arms_rankable"):
        raise ValueError("quality result is not fully rankable")
    quality_arms = {arm["arm"]: arm for arm in quality["arms"]}
    cost_arms = {arm["arm"]: arm for arm in cost["arms"]}
    evidence, navigation = quality_arms[EVIDENCE_ARM], quality_arms[NAVIGATION_ARM]
    evidence_trace = trace_stats(run, EVIDENCE_ARM)
    navigation_trace = trace_stats(run, NAVIGATION_ARM, navigation_expected=True)
    evidence_families, navigation_families = (
        family_success(evidence), family_success(navigation)
    )
    family_deltas = [
        {
            "family": family,
            "navigation": navigation_families[family],
            "evidence": evidence_families[family],
            "navigation_minus_evidence": (
                navigation_families[family] - evidence_families[family]
            ),
        }
        for family in evidence_families
    ]
    gates = {
        "strict_success_non_decreasing": (
            navigation["strict_success_macro"] >= evidence["strict_success_macro"]
        ),
        "citation_accuracy_non_decreasing": (
            metric(navigation, "citation_accuracy")
            >= metric(evidence, "citation_accuracy")
        ),
        "required_evidence_recall_non_decreasing": (
            metric(navigation, "required_evidence_recall")
            >= metric(evidence, "required_evidence_recall")
        ),
        "navigation_read_sources_rate_at_least_95_percent": (
            navigation_trace["read_sources_rate"] >= 0.95
        ),
        "navigation_returns_no_original_text": (
            not navigation_trace["navigation_original_text_leaks"]
            and not navigation_trace["invalid_successful_navigation_payloads"]
        ),
        "first_locate_characters_reduced": (
            navigation_trace["first_locate_mean_characters"]
            < evidence_trace["first_locate_mean_characters"]
        ),
    }
    paired = next(
        row for row in quality["paired_comparisons"]
        if row["first"][0] == EVIDENCE_ARM
        and row["second"][0] == NAVIGATION_ARM
    )
    return {
        "schema": "chapter2-navigation-mode-replacement-gate-v1",
        "protocol_sha256": sha256(run / "protocol.json"),
        "quality_sha256": sha256(quality_path),
        "cost_sha256": sha256(cost_path),
        "scope": "post-hoc v5 development comparison; holdout remains unopened",
        "methods": {
            EVIDENCE_ARM: {
                "strict_success_macro": evidence["strict_success_macro"],
                "strict_success_95ci": evidence["strict_success_95ci"],
                "citation_accuracy": metric(evidence, "citation_accuracy"),
                "required_evidence_recall": metric(
                    evidence, "required_evidence_recall"
                ),
                "cross_source_completeness": metric(
                    evidence, "cross_source_completeness"
                ),
                "reported_usage": cost_arms[EVIDENCE_ARM]["reported_usage"],
                "trace": evidence_trace,
            },
            NAVIGATION_ARM: {
                "strict_success_macro": navigation["strict_success_macro"],
                "strict_success_95ci": navigation["strict_success_95ci"],
                "citation_accuracy": metric(navigation, "citation_accuracy"),
                "required_evidence_recall": metric(
                    navigation, "required_evidence_recall"
                ),
                "cross_source_completeness": metric(
                    navigation, "cross_source_completeness"
                ),
                "reported_usage": cost_arms[NAVIGATION_ARM]["reported_usage"],
                "trace": navigation_trace,
            },
        },
        "navigation_minus_evidence": {
            "strict_success_macro": (
                navigation["strict_success_macro"] - evidence["strict_success_macro"]
            ),
            "citation_accuracy": (
                metric(navigation, "citation_accuracy")
                - metric(evidence, "citation_accuracy")
            ),
            "required_evidence_recall": (
                metric(navigation, "required_evidence_recall")
                - metric(evidence, "required_evidence_recall")
            ),
            "cross_source_completeness": (
                metric(navigation, "cross_source_completeness")
                - metric(evidence, "cross_source_completeness")
            ),
            "paired_family_95ci": [
                -paired["paired_family_95ci"][1],
                -paired["paired_family_95ci"][0],
            ],
            "first_locate_mean_characters": (
                navigation_trace["first_locate_mean_characters"]
                - evidence_trace["first_locate_mean_characters"]
            ),
            "total_returned_mean_characters": (
                navigation_trace["total_returned_mean_characters"]
                - evidence_trace["total_returned_mean_characters"]
            ),
            "reported_total_tokens": (
                cost_arms[NAVIGATION_ARM]["reported_usage"]["total_tokens"]
                - cost_arms[EVIDENCE_ARM]["reported_usage"]["total_tokens"]
            ),
        },
        "family_deltas": sorted(
            family_deltas,
            key=lambda row: (row["navigation_minus_evidence"], row["family"]),
        ),
        "gates": gates,
        "replacement_approved": all(gates.values()),
        "decision": (
            "replace_default_with_navigation"
            if all(gates.values())
            else "retain_evidence_first_default"
        ),
        "holdout_unlocked": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--cost", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compile_gate(
        args.run.resolve(), args.quality.resolve(), args.cost.resolve()
    )
    audit.save(args.output.resolve(), result)
    print(json.dumps({
        "replacement_approved": result["replacement_approved"],
        "decision": result["decision"],
        "gates": result["gates"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
