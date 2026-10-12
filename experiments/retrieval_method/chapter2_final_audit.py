"""Audit the frozen Chapter 2 development, ablation, holdout, and cost evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import leaderboard_admission as admission
import leaderboard_audit as audit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def metric(row, name):
    return row["metrics"][name]["macro_over_applicable_categories"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leaderboard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.leaderboard.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    runs = {
        "baseline": root / "runs/current_methods_flash_v11",
        "candidate": root / "runs/candidate_flash_v14",
        "ablation": root / "runs/candidate_ablation_flash_v1",
        "holdout": root / "final-evaluation-flash-v1/runs/final_holdout_flash_v1_baseline",
    }
    expected_sessions = {"baseline": 864, "candidate": 216, "ablation": 972, "holdout": 144}
    admissions = {}
    protocols = {}
    for name, run in runs.items():
        protocols[name] = audit.verify(run)
        require(protocols[name].get("model") == "deepseek-flash", f"{name} protocol model drift")
        require(protocols[name].get("planned_sessions") == expected_sessions[name],
                f"{name} planned grid drift")
        admissions[name] = admission.check(run)
        require(admissions[name]["passed"], f"{name} replay admission failed")
        require(set(admissions[name]["provider_models"]) == {"deepseek-flash"},
                f"{name} response model drift")

    quality_paths = {
        "baseline": root / "baseline-flash-followup-v11/quality.json",
        "candidate": root / "candidate-flash-followup-v11/candidate-quality.json",
        "ablation": root / "candidate-ablation-flash-analysis-v1/ablation-quality.json",
        "holdout": root / "final-evaluation-flash-v1/baseline-quality.json",
    }
    expected_arms = {"baseline": 8, "candidate": 2, "ablation": 9, "holdout": 2}
    qualities = {}
    for name, path in quality_paths.items():
        report = audit.read(path)
        qualities[name] = report
        require(report["all_arms_rankable"] and report["model_identity_compatible"],
                f"{name} quality is not rankable")
        require(len(report["arms"]) == expected_arms[name], f"{name} arm count drift")
        require(report["protocol_sha256"] == audit.sha(runs[name] / "protocol.json"),
                f"{name} quality protocol binding drift")

    review_models = Counter()
    review_statuses = Counter()
    review_protocols = {}
    for protocol_path in sorted((root / "reviews").glob("*/protocol.json")):
        model = audit.read(protocol_path).get("model")
        review_protocols[protocol_path.parent.name] = model
        require(model == "deepseek-flash", "development review protocol model drift")
    holdout_review_root = root / "final-evaluation-flash-v1/reviews"
    for protocol_path in sorted(holdout_review_root.glob("*/protocol.json")):
        model = audit.read(protocol_path).get("model")
        review_protocols["holdout/" + protocol_path.parent.name] = model
        require(model == "deepseek-flash", "holdout review protocol model drift")
    for review_root in (root / "reviews", holdout_review_root):
        for path in review_root.glob("*/sessions/*/*.json"):
            record = audit.read(path)
            if "request_sha256" not in record:
                continue
            review_models[record.get("request", {}).get("model")] += 1
            review_statuses[record.get("status")] += 1
    require(set(review_models) == {"deepseek-flash"}, "review response model drift")

    semantic_protocols = sorted((root / "candidate").glob("semantics*/protocol.json"))
    require(semantic_protocols, "candidate semantic construction provenance missing")
    for path in semantic_protocols:
        protocol = audit.read(path)
        require(protocol.get("gold_or_questions_used") is False, "gold/questions entered graph construction")
        require(protocol.get("holdout_opened") is False, "holdout entered graph construction")

    final_root = root / "final-evaluation-flash-v1"
    state = audit.read(final_root / "state.json")
    gate_path = final_root / "final-method-freeze-v1/implementation-gate.json"
    gate = audit.read(gate_path)
    require(state.get("completed") and state.get("status") == "holdout_evaluation_complete",
            "final evaluation is incomplete")
    require(gate["implementation_frozen"] and gate["selection_rule_applied_without_holdout"],
            "final implementation was not frozen before holdout")
    require(gate["selected"]["arm"] == "GN" and gate["selected"]["method"] == "graph_first",
            "unexpected final method")
    registration = root / "final-method-selection-preregistration-v1.json"
    require(gate["selection_registration_sha256"] == audit.sha(registration),
            "selection preregistration binding drift")

    final_results_path = final_root / "results/final-holdout-results.json"
    final_results = audit.read(final_results_path)
    require(state["final_results_sha256"] == audit.sha(final_results_path), "final result state binding drift")
    require(final_results["holdout_included"] and not final_results["development_scores_included"],
            "holdout/development result separation failed")
    require(final_results["identity"]["model"] == "deepseek-flash", "holdout identity model drift")

    cost_path = final_root / "results/cost-report/final-cost-summary.json"
    costs = audit.read(cost_path)
    require(state["final_cost_summary_sha256"] == audit.sha(cost_path), "final cost state binding drift")
    require(costs["model"] == "deepseek-flash" and costs["actual_invoice_cost_usd"] is None,
            "cost model or unknown-invoice policy drift")
    for ledger_name in ("development_flash_campaign", "holdout_flash_campaign"):
        require(costs[ledger_name]["actual_invoice_cost_usd"] is None,
                "unknown campaign invoice was replaced by a number")
    require("inherited_duplicates_excluded" in costs["development_review_overhead"],
            "review recovery duplicates were not audited")

    holdout_rows = {(row["arm"], row["method"]): row for row in final_results["arms"]}
    gn = holdout_rows[("GN", "graph_first")]
    control = holdout_rows[("control", "no_graph")]
    pair = next(row for row in final_results["paired_comparisons"]
                if {tuple(row["first"][-2:]), tuple(row["second"][-2:])}
                == {("GN", "graph_first"), ("control", "no_graph")})
    if tuple(pair["first"][-2:]) == ("GN", "graph_first"):
        paired_ci = pair["paired_family_95ci"]
    else:
        paired_ci = [-pair["paired_family_95ci"][1], -pair["paired_family_95ci"][0]]
    result = {
        "schema": "chapter2-final-evidence-audit-v1",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "model": "deepseek-flash",
        "formal_run_admission": {
            name: {
                "protocol_sha256": audit.sha(runs[name] / "protocol.json"),
                "planned_sessions": report["expected"],
                "answers": report["answers"],
                "terminal_failures": report["terminal_failures"],
                "replayed": report["replayed"],
                "provider_models": report["provider_models"],
            }
            for name, report in admissions.items()
        },
        "rankable_arms": {name: len(report["arms"]) for name, report in qualities.items()},
        "review_protocol_count": len(review_protocols),
        "review_request_models": dict(review_models),
        "review_request_statuses": dict(review_statuses),
        "candidate_construction": {
            "semantic_protocols": [str(path) for path in semantic_protocols],
            "gold_or_questions_used": False,
            "holdout_opened": False,
        },
        "final_method": gate["selected"],
        "holdout": {
            "fact_families": final_results["holdout_fact_families"],
            "GN": {
                "strict_success_macro": gn["strict_success_macro"],
                "strict_success_95ci": gn["strict_success_95ci"],
                "citation_accuracy": metric(gn, "citation_accuracy"),
                "cross_source_completeness": metric(gn, "cross_source_completeness"),
            },
            "control": {
                "strict_success_macro": control["strict_success_macro"],
                "strict_success_95ci": control["strict_success_95ci"],
                "citation_accuracy": metric(control, "citation_accuracy"),
                "cross_source_completeness": metric(control, "cross_source_completeness"),
            },
            "GN_minus_control_strict_success": gn["strict_success_macro"] - control["strict_success_macro"],
            "paired_family_95ci_GN_minus_control": paired_ci,
        },
        "cost_summary_sha256": audit.sha(cost_path),
        "bindings": {
            "selection_registration": audit.sha(registration),
            "implementation_gate": audit.sha(gate_path),
            "final_holdout_results": audit.sha(final_results_path),
            **{name + "_quality": audit.sha(path) for name, path in quality_paths.items()},
        },
        "limitations": [
            "The holdout paired interval touches zero, so the observed GN advantage is not claimed statistically significant.",
            "Source judges use the same model family as answer generation and are not independent human validation.",
            "Provider attempts with missing usage, hardware, electricity, and invoice adjustments remain unknown.",
        ],
    }
    audit.save(output / "final-audit.json", result)
    print("PASS: Chapter 2 final evidence audit")


if __name__ == "__main__":
    main()
