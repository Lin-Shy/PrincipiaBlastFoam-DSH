"""Combine admitted holdout cohorts without mixing development scores into the result."""
from __future__ import annotations

import argparse
from pathlib import Path

import leaderboard_audit as audit
import leaderboard_comparison as comparison


def percent(value):
    return "—" if value is None else f"{100 * value:.1f}%"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--evaluation", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    evaluation = args.evaluation.resolve()
    state = audit.read(evaluation / "state.json")
    if not state.get("completed") or state.get("status") != "holdout_evaluation_complete":
        raise ValueError("holdout evaluation is not complete")
    gate_path = evaluation / "final-method-freeze-v1/implementation-gate.json"
    gate = audit.read(gate_path)
    roots, reports, names, costs, bindings = [], [], [], {}, []
    for cohort in state["cohorts"]:
        name = cohort["kind"]
        root = Path(cohort["run"])
        quality_path = evaluation / f"{name}-quality.json"
        cost_path = evaluation / f"{name}-cost-and-grid.json"
        report = audit.read(quality_path)
        if audit.sha(quality_path) != cohort["quality_sha256"] or not report["all_arms_rankable"]:
            raise ValueError("holdout quality binding failed")
        cost = audit.read(cost_path)
        if audit.sha(cost_path) != cohort["cost_sha256"]:
            raise ValueError("holdout cost binding failed")
        roots.append(root); reports.append(report); names.append(name)
        for row in cost["arms"]:
            costs[(name, row["arm"], row["method"])] = row
        bindings.append({"cohort": name, "run_protocol_sha256": audit.sha(root / "protocol.json"),
                         "quality_sha256": audit.sha(quality_path), "cost_sha256": audit.sha(cost_path)})
    combined = comparison.combine(roots, reports, names)
    family_count = len({session["family"] for report in reports
                        for row in report["arms"] for session in row["sessions"]})
    combined.update(schema="chapter2-final-holdout-results-v1", holdout_included=True,
                    development_scores_included=False, final_method_gate_sha256=audit.sha(gate_path),
                    selected_final=gate["selected"], source_cohorts=bindings,
                    holdout_fact_families=family_count,
                    comparison_scope="Frozen final method and preregistered holdout controls on the previously unopened split; development scores are excluded.",
                    uncertainty=f"Pointwise paired bootstrap intervals over {family_count} holdout fact families; same-model-family source judges, not independent-human validation.")
    for row in combined["arms"]:
        cost = costs[(row["cohort"], row["arm"], row["method"])]
        row["reported_answer_usage"] = cost["reported_usage"]
        row["unknown_usage_attempts"] = cost["unknown_usage_attempts"]
        row["actual_currency_cost"] = None
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    audit.save(output / "final-holdout-results.json", combined)
    selected = gate["selected"]
    lines = ["# 第2章冻结方法留出集结果", "",
             "本表只包含最终方法冻结后打开的留出集结果，不并入开发集分数。所有配置使用 `deepseek-flash`、相同题目、三次重复、公共检索预算、来源评审与零模型重放准入。", "",
             "| 配置 | 是否最终方法 | 严格成功率 | 引用质量 | 跨来源能力 | 已报告回答 token | 未知用量尝试 |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in combined["arms"]:
        is_selected = row["arm"] == selected["arm"] and row["method"] == selected["method"]
        m = row["metrics"]
        usage = row["reported_answer_usage"].get("total_tokens")
        lines.append("| " + " | ".join([
            f"`{row['arm']}/{row['method']}`", "是" if is_selected else "否",
            percent(row["strict_success_macro"]),
            percent(m["citation_accuracy"]["macro_over_applicable_categories"]),
            percent(m["cross_source_completeness"]["macro_over_applicable_categories"]),
            f"{usage:,}" if usage is not None else "未知",
            str(row["unknown_usage_attempts"]),
        ]) + " |")
    lines += ["", "实际货币费用保持为空，因为供应商中断尝试可能存在未知用量；已报告 token 与未知尝试分开保留。来源评审使用同模型家族并做方法盲化，不等同独立领域专家复核。", "",
              f"最终方法冻结门 SHA-256：`{audit.sha(gate_path)}`；留出结果 SHA-256：`{audit.sha(output / 'final-holdout-results.json')}`。", ""]
    (output / "留出集结果.md").write_text("\n".join(lines))
    print("PASS: admitted frozen holdout results combined")


if __name__ == "__main__":
    main()
