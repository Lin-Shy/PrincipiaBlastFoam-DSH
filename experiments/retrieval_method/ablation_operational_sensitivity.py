"""Bound preregistered ablation effects under observed terminal transport failures."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import statistics

import leaderboard_audit as audit
from ablation_results import SINGLES


def strict_macro(row, terminal_value=False):
    categories = defaultdict(list)
    for session in row["sessions"]:
        value = bool(session["quality"]["qa_success"])
        if session["state"] == "tested_terminal_failure":
            value = terminal_value
        categories[session["category"]].append(int(value))
    return statistics.mean(statistics.mean(values) for values in categories.values())


def analyze(reference, ablations):
    if not reference.get("all_arms_rankable") or not ablations.get("all_arms_rankable"):
        raise ValueError("admitted reference and ablation quality reports are required")
    full = next(row for row in reference["arms"] if row["arm"] == "full_candidate")
    full_observed = strict_macro(full, False)
    rows = {row["arm"]: row for row in ablations["arms"]}
    result = {}
    for component, arm in SINGLES.items():
        row = rows[arm]
        terminal = [session for session in row["sessions"]
                    if session["state"] == "tested_terminal_failure"]
        observed = strict_macro(row, False)
        optimistic = strict_macro(row, True)
        result[component] = {
            "ablated_arm": arm,
            "terminal_transport_failures": len(terminal),
            "terminal_failures_by_category": dict(Counter(session["category"] for session in terminal)),
            "removed_arm_observed_strict_success": observed,
            "removed_arm_if_all_terminal_transports_succeeded": optimistic,
            "component_effect_full_minus_removed_observed": full_observed - observed,
            "component_effect_transport_sensitivity_bounds": [full_observed - optimistic,
                                                               full_observed - observed],
        }
    return {
        "schema": "candidate-ablation-terminal-transport-sensitivity-v1",
        "primary_analysis_changed": False,
        "full_candidate_strict_success": full_observed,
        "components": result,
        "interpretation": "The primary frozen policy counts exhausted transport requests as strict failures. Bounds leave the observed result unchanged at one endpoint and set every terminal transport failure in the removed-component arm to success at the other; they are a service-disturbance sensitivity check, not replacement scores.",
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--reference-quality", type=Path, required=True)
    cli.add_argument("--ablation-quality", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    result = analyze(audit.read(args.reference_quality), audit.read(args.ablation_quality))
    audit.save(args.output, result)
    print("PASS: terminal transport sensitivity bounds")


if __name__ == "__main__":
    main()
