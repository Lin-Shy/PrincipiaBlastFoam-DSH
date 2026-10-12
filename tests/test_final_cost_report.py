import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "experiments/retrieval_method/final_cost_report.py"


def write(path, value):
    path.write_text(json.dumps(value))


def test_final_cost_report_separates_answer_review_and_historical_build_costs(tmp_path):
    stage = {"reported_usage": {"total_tokens": 50}, "priced_attempts": 2,
             "unpriced_attempts": 1, "reported_usage_usd_interval": [0.1, 0.2]}
    campaign = {"priced_attempts": 2, "unpriced_flash_attempts": 1,
                "reported_usage_usd_interval": [0.1, 0.2]}
    dev = tmp_path / "dev.json"; hold = tmp_path / "hold.json"
    write(dev, {"stages": {"review/r": stage, "construction/semantics": {
        **stage, "reported_usage": {"total_tokens": 70}}},
        "unique_review_attempts": {**stage, "reported_usage": {"total_tokens": 40},
                                     "inherited_duplicates_excluded": 3},
        "unique_flash_experiment_attempts": campaign,
        "original_graphify_build_stages": {"native": {"reported_usage": {"total_tokens": 30}}},
        "deterministic_structure_build": {"accounting": {"model_requests": 0}}})
    write(hold, {"stages": {"review/h": stage}, "unique_flash_experiment_attempts": campaign,
                 "original_graphify_build_stages": {}, "deterministic_structure_build": None})
    baseline = tmp_path / "baseline.json"; candidate = tmp_path / "candidate.json"
    ablation = tmp_path / "ablation.json"; results = tmp_path / "results.json"
    write(baseline, {"arms": [{"arm": "GN", "method": "graph_first",
                                "reported_usage": {"total_tokens": 100}, "unknown_usage_attempts": 1}]})
    write(candidate, {"arms": [{"arm": "full_candidate", "method": "retrieval_first",
                                 "reported_usage": {"total_tokens": 120}, "unknown_usage_attempts": 2}]})
    write(ablation, {"arms": [{"arm": "minus_paths", "method": "retrieval_first",
                                "reported_usage": {"total_tokens": 110}, "unknown_usage_attempts": 3}]})
    write(results, {"arms": [{"cohort": "baseline", "arm": "GN", "method": "graph_first",
                               "reported_answer_usage": {"total_tokens": 80}, "unknown_usage_attempts": 0}]})
    output = tmp_path / "out"
    subprocess.run([sys.executable, str(SCRIPT), "--development-ledger", str(dev),
                    "--holdout-ledger", str(hold), "--baseline-cost", str(baseline),
                    "--candidate-cost", str(candidate), "--ablation-cost", str(ablation),
                    "--holdout-results", str(results), "--output", str(output)], check=True)
    summary = json.loads((output / "final-cost-summary.json").read_text())
    assert summary["development_answer_methods"][0]["reported_usage"]["total_tokens"] == 100
    assert summary["development_review_overhead"]["reported_usage"]["total_tokens"] == 40
    assert summary["development_review_overhead"]["inherited_duplicates_excluded"] == 3
    assert summary["construction"]["historical_graphify_reported_tokens"] == 30
    assert summary["construction"]["historical_candidate_semantic_reported_tokens"] == 70
    assert summary["actual_invoice_cost_usd"] is None
    assert "不计入本轮Flash实验费用" in (output / "最终成本报告.md").read_text()
    assert "排除 3 个恢复代继承的重复请求记录" in (output / "最终成本报告.md").read_text()
