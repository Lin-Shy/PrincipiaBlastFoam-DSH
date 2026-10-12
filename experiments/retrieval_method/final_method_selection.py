"""Apply the preregistered development rule and freeze one method before holdout."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(row, name):
    return row["metrics"][name]["macro_over_applicable_categories"]


def find_row(report, arm, method="retrieval_first"):
    rows = [r for r in report["arms"] if r["arm"] == arm and r["method"] == method]
    if len(rows) != 1:
        raise ValueError(f"expected one quality row for {arm}/{method}")
    return rows[0]


def cost_tokens(report, arm, method):
    rows = [r for r in report["arms"] if r["arm"] == arm and r["method"] == method]
    if len(rows) != 1:
        raise ValueError(f"expected one cost row for {arm}/{method}")
    return rows[0].get("reported_usage", {}).get("total_tokens")


def identity(row, tokens, source, method):
    return {
        "arm": row["arm"],
        "method": method,
        "source": source,
        "strict_success_macro": row["strict_success_macro"],
        "citation_accuracy": metric(row, "citation_accuracy"),
        "cross_source_completeness": metric(row, "cross_source_completeness"),
        "reported_answer_total_tokens": tokens,
    }


def verify_registered_artifacts(registration):
    for name, item in registration["development_artifacts"].items():
        path = Path(item["path"])
        if sha(path) != item["sha256"]:
            raise ValueError(f"registered development artifact changed: {name}")


def require_registered_input(registration, name, supplied: Path):
    item = registration["development_artifacts"][name]
    supplied = supplied.resolve()
    if supplied != Path(item["path"]).resolve() or sha(supplied) != item["sha256"]:
        raise ValueError(f"selection input is not the registered {name}")


def require_report_protocol(report, expected, name):
    if report.get("protocol_sha256") != expected:
        raise ValueError(f"{name} does not bind the registered run protocol")


def select(registration, baseline, baseline_cost, candidate, candidate_cost,
           ablation, ablation_cost):
    if registration["model"] != "deepseek-flash":
        raise ValueError("final selection must use deepseek-flash")
    for name, report in (("baseline", baseline), ("candidate", candidate), ("ablation", ablation)):
        if not report.get("all_arms_rankable"):
            raise ValueError(f"{name} development report is not fully admitted")

    incumbent_row = find_row(baseline, "GN", "graph_first")
    incumbent = identity(incumbent_row, cost_tokens(baseline_cost, "GN", "graph_first"),
                         "baseline", "graph_first")
    candidates = []
    for arm in registration["candidate_eligible_arms"]:
        report, costs, source = ((candidate, candidate_cost, "candidate")
                                 if arm == "full_candidate"
                                 else (ablation, ablation_cost, "ablation"))
        row = find_row(report, arm)
        item = identity(row, cost_tokens(costs, arm, "retrieval_first"), source,
                        "retrieval_first")
        thresholds = registration["selection_rule"]["switch_from_incumbent_only_if"]
        item["margins_vs_incumbent"] = {
            "strict_success_macro": item["strict_success_macro"] - incumbent["strict_success_macro"],
            "citation_accuracy": item["citation_accuracy"] - incumbent["citation_accuracy"],
            "cross_source_completeness": item["cross_source_completeness"] - incumbent["cross_source_completeness"],
        }
        threshold_metrics = {
            "strict_success_macro_margin_at_least": "strict_success_macro",
            "citation_accuracy_margin_at_least": "citation_accuracy",
            "cross_source_completeness_margin_at_least": "cross_source_completeness",
        }
        if set(thresholds) != set(threshold_metrics):
            raise ValueError("unrecognized registered selection thresholds")
        item["eligible_to_replace_incumbent"] = all(
            item["margins_vs_incumbent"][threshold_metrics[key]] >= value
            for key, value in thresholds.items())
        candidates.append(item)

    eligible = [item for item in candidates if item["eligible_to_replace_incumbent"]]
    eligible.sort(key=lambda item: (
        -item["strict_success_macro"], -item["cross_source_completeness"],
        -item["citation_accuracy"],
        item["reported_answer_total_tokens"] if item["reported_answer_total_tokens"] is not None else float("inf"),
        item["arm"],
    ))
    selected = eligible[0] if eligible else incumbent
    return incumbent, candidates, selected


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("registration", "baseline-quality", "baseline-cost", "candidate-quality",
                 "candidate-cost", "ablation-quality", "ablation-cost", "baseline-run",
                 "candidate-run", "ablation-run", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("preserve the first final-method freeze")
    registration = read(args.registration.resolve())
    verify_registered_artifacts(registration)
    for argument, registered in (("baseline_quality", "baseline_quality"),
                                 ("baseline_cost", "baseline_cost"),
                                 ("candidate_quality", "candidate_quality"),
                                 ("candidate_cost", "candidate_cost")):
        require_registered_input(registration, registered, getattr(args, argument))
    reports = [read(getattr(args, name).resolve()) for name in
               ("baseline_quality", "baseline_cost", "candidate_quality", "candidate_cost",
                "ablation_quality", "ablation_cost")]
    baseline_protocol = registration["development_artifacts"]["baseline_protocol"]["sha256"]
    candidate_protocol = registration["development_artifacts"]["candidate_protocol"]["sha256"]
    ablation_protocol = registration["development_artifacts"]["ablation_protocol"]["sha256"]
    for report, expected, name in ((reports[0], baseline_protocol, "baseline quality"),
                                   (reports[1], baseline_protocol, "baseline cost"),
                                   (reports[2], candidate_protocol, "candidate quality"),
                                   (reports[3], candidate_protocol, "candidate cost"),
                                   (reports[4], ablation_protocol, "ablation quality"),
                                   (reports[5], ablation_protocol, "ablation cost")):
        require_report_protocol(report, expected, name)
    for run_name, registered in (("baseline_run", "baseline_protocol"),
                                 ("candidate_run", "candidate_protocol"),
                                 ("ablation_run", "ablation_protocol")):
        run = getattr(args, run_name).resolve()
        item = registration["development_artifacts"][registered]
        if run / "protocol.json" != Path(item["path"]).resolve() or sha(run / "protocol.json") != item["sha256"]:
            raise ValueError(f"selection source is not the registered {run_name}")
    incumbent, candidates, selected = select(registration, *reports)
    runs = {"baseline": args.baseline_run.resolve(), "candidate": args.candidate_run.resolve(),
            "ablation": args.ablation_run.resolve()}
    source_root = runs[selected["source"]]
    source_protocol = read(source_root / "protocol.json")
    if source_protocol.get("model") != "deepseek-flash":
        raise ValueError("selected source protocol model changed")
    output.mkdir(parents=True)
    holdout_runner = Path(__file__).with_name("final_holdout.py").resolve()
    result = {
        "schema": "chapter2-final-method-freeze-v1",
        "implementation_frozen": True,
        "holdout_opened": False,
        "selection_registration_sha256": sha(args.registration.resolve()),
        "development_reports": {
            name: {"path": str(getattr(args, name).resolve()),
                   "sha256": sha(getattr(args, name).resolve())}
            for name in ("baseline_quality", "baseline_cost", "candidate_quality", "candidate_cost",
                         "ablation_quality", "ablation_cost")
        },
        "dev_runs": {name: {"path": str(path), "protocol_sha256": sha(path / "protocol.json")}
                     for name, path in runs.items()},
        "incumbent": incumbent,
        "candidate_decisions": candidates,
        "selected": {**selected, "source_run": str(source_root),
                     "source_protocol_sha256": sha(source_root / "protocol.json"),
                     "source_arm_protocol_sha256": sha(source_root / selected["arm"] / "protocol.json")},
        "selection_rule_applied_without_holdout": True,
        "selection_runner_sha256": sha(Path(__file__).resolve()),
        "model": "deepseek-flash",
        "holdout_runner": str(holdout_runner),
        "holdout_runner_sha256": sha(holdout_runner),
    }
    (output / "implementation-gate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"selected": result["selected"],
                      "gate_sha256": sha(output / "implementation-gate.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
