"""Write a human-readable final cost report from frozen answer and campaign ledgers."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import leaderboard_audit as audit


def sum_usage(rows):
    total = Counter()
    for row in rows:
        total.update(row.get("reported_usage", {}))
    return dict(total)


def money(value):
    if not value:
        return "未知"
    return f"US${value[0]:.4f}" if value[0] == value[1] else f"US${value[0]:.4f}–{value[1]:.4f}"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("development-ledger", "holdout-ledger", "baseline-cost", "candidate-cost",
                 "ablation-cost", "holdout-results", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    dev_ledger = audit.read(args.development_ledger)
    holdout_ledger = audit.read(args.holdout_ledger)
    answer_reports = [("基线", audit.read(args.baseline_cost)),
                      ("完整候选", audit.read(args.candidate_cost)),
                      ("消融", audit.read(args.ablation_cost))]
    holdout = audit.read(args.holdout_results)
    dev_rows = []
    for cohort, report in answer_reports:
        for row in report["arms"]:
            dev_rows.append({"cohort": cohort, "arm": row["arm"], "method": row["method"],
                             "reported_usage": row["reported_usage"],
                             "unknown_usage_attempts": row["unknown_usage_attempts"]})
    holdout_rows = [{"cohort": row["cohort"], "arm": row["arm"], "method": row["method"],
                     "reported_usage": row["reported_answer_usage"],
                     "unknown_usage_attempts": row["unknown_usage_attempts"]}
                    for row in holdout["arms"]]

    def review_summary(ledger):
        if "unique_review_attempts" in ledger:
            return ledger["unique_review_attempts"]
        rows = [row for name, row in ledger["stages"].items() if name.startswith("review/")]
        amounts = [row["reported_usage_usd_interval"] for row in rows
                   if row.get("reported_usage_usd_interval")]
        return {"reported_usage": sum_usage(rows),
                "priced_attempts": sum(row["priced_attempts"] for row in rows),
                "unpriced_attempts": sum(row["unpriced_attempts"] for row in rows),
                "reported_usage_usd_interval": ([sum(x[0] for x in amounts), sum(x[1] for x in amounts)]
                                                 if amounts else None)}

    historical_build_tokens = sum(
        row.get("reported_usage", {}).get("total_tokens", 0)
        for row in dev_ledger.get("original_graphify_build_stages", {}).values())
    candidate_build_rows = [row for name, row in dev_ledger["stages"].items()
                            if name.startswith("construction/")]
    candidate_build_tokens = sum(row.get("reported_usage", {}).get("total_tokens", 0)
                                 for row in candidate_build_rows)
    summary = {
        "schema": "chapter2-final-cost-summary-v1",
        "model": "deepseek-flash",
        "development_answer_methods": dev_rows,
        "holdout_answer_methods": holdout_rows,
        "development_review_overhead": review_summary(dev_ledger),
        "holdout_review_overhead": review_summary(holdout_ledger),
        "development_flash_campaign": dev_ledger["unique_flash_experiment_attempts"],
        "holdout_flash_campaign": holdout_ledger["unique_flash_experiment_attempts"],
        "construction": {
            "deterministic_gn_gh": dev_ledger.get("deterministic_structure_build"),
            "historical_graphify_reported_tokens": historical_build_tokens,
            "historical_candidate_semantic_reported_tokens": candidate_build_tokens,
            "historical_construction_in_flash_campaign_total": False,
        },
        "bindings": {name: {"path": str(getattr(args, name).resolve()),
                             "sha256": audit.sha(getattr(args, name).resolve())}
                     for name in ("development_ledger", "holdout_ledger", "baseline_cost",
                                  "candidate_cost", "ablation_cost", "holdout_results")},
        "actual_invoice_cost_usd": None,
        "missing_policy": "Unknown provider usage, hardware, electricity and invoice adjustments remain unknown and are never replaced by zero.",
    }
    audit.save(output / "final-cost-summary.json", summary)
    lines = ["# 第2章最终成本报告", "",
             "方法成本以回答阶段供应商已报告 token 为主，构图与评审成本分开列示。未知用量、硬件、电力和账单调整保持未知，不记作零。", "",
             "## 开发集回答成本", "",
             "| 队列 | 配置 | 已报告 token | 未知用量尝试 |", "|---|---|---:|---:|"]
    for row in dev_rows:
        tokens = row["reported_usage"].get("total_tokens")
        lines.append(f"| {row['cohort']} | `{row['arm']}/{row['method']}` | "
                     f"{tokens:,} | {row['unknown_usage_attempts']} |")
    lines += ["", "## 留出集回答成本", "",
              "| 队列 | 配置 | 已报告 token | 未知用量尝试 |", "|---|---|---:|---:|"]
    for row in holdout_rows:
        tokens = row["reported_usage"].get("total_tokens")
        lines.append(f"| {row['cohort']} | `{row['arm']}/{row['method']}` | "
                     f"{tokens:,} | {row['unknown_usage_attempts']} |")
    lines += ["", "## 评测与构图开销", ""]
    for label, value in (("开发集盲审与仲裁", summary["development_review_overhead"]),
                         ("留出集盲审与仲裁", summary["holdout_review_overhead"])):
        tokens = value["reported_usage"].get("total_tokens", 0)
        lines.append(f"- {label}：已报告 {tokens:,} token，{value['unpriced_attempts']} 个尝试无法定价，"
                     f"已报告用量估价 {money(value['reported_usage_usd_interval'])}；"
                     f"排除 {value.get('inherited_duplicates_excluded', 0)} 个恢复代继承的重复请求记录。")
    lines += [
        f"- GN/GH增量结构构建：{0 if summary['construction']['deterministic_gn_gh'] else '未知'} 次模型调用；确定性读写与耗时见绑定账本。",
        f"- Graphify父图历史构建：已报告 {historical_build_tokens:,} token；属于冻结输入的历史其他模型调用，不计入本轮Flash实验费用。",
        f"- 候选语义层历史构建：已报告 {candidate_build_tokens:,} token；属于冻结输入的历史其他模型调用，不计入本轮Flash实验费用。",
        "", "## Flash实验总账", ""]
    for label, value in (("开发与消融", summary["development_flash_campaign"]),
                         ("留出集", summary["holdout_flash_campaign"])):
        lines.append(f"- {label}：{value['priced_attempts']} 个可定价尝试，"
                     f"{value['unpriced_flash_attempts']} 个Flash尝试缺少完整用量；"
                     f"已报告用量估价 {money(value['reported_usage_usd_interval'])}。")
    lines += ["", "上述美元数是按冻结公开价对已报告用量的重建，不是账户发票；只要存在未知尝试，就不能声称这是完整实际费用。", "",
              f"成本摘要 SHA-256：`{audit.sha(output / 'final-cost-summary.json')}`。", ""]
    (output / "最终成本报告.md").write_text("\n".join(lines))
    print("PASS: final cost report")


if __name__ == "__main__":
    main()
