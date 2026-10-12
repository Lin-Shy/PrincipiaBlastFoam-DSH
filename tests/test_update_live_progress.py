import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

from update_live_progress import refresh, refresh_final


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_ablation_progress_reports_zero_model_replay_count(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text(
        "> 最后更新：old  \n"
        "| 消融实验 | 0 / 972 | old |\n"
    )
    run = tmp_path / "run"
    (run / "arm" / "sessions" / "one").mkdir(parents=True)
    (run / "arm" / "sessions" / "one" / "result.json").write_text("{}")
    followup = tmp_path / "followup"
    followup.mkdir()
    (followup / "state.json").write_text(json.dumps({"status": "ablation_zero_model_replay_parallel"}))
    (followup / "replay-parallel.log").write_text("DONE one complete\nERROR two RuntimeError\n")

    refresh(doc, run, followup)

    text = doc.read_text()
    assert "| 消融实验 | 1 / 972 | 回答完成，零模型重放 2 / 972（1 个预期或异常终止项） |" in text


def test_ablation_progress_reports_compiled_source_reviews(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text(
        "> 最后更新：old  \n"
        "| 消融实验 | 0 / 972 | old |\n"
    )
    run = tmp_path / "run"
    (run / "arm" / "sessions" / "one").mkdir(parents=True)
    (run / "arm" / "sessions" / "one" / "result.json").write_text("{}")
    followup = tmp_path / "leaderboard" / "candidate-ablation-flash-followup-v1"
    followup.mkdir(parents=True)
    (followup / "state.json").write_text(json.dumps({"status": "ablation_source_review_1"}))
    sessions = tmp_path / "leaderboard" / "reviews" / "candidate_ablation_flash_v1" / "sessions"
    (sessions / "one").mkdir(parents=True)
    (sessions / "one" / "compiled.json").write_text("{}")

    refresh(doc, run, followup)

    assert "| 消融实验 | 1 / 972 | 重放通过，来源盲审已汇总 1 / 969 |" in doc.read_text()


def test_ablation_progress_uses_effective_recovery_reviews(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text("> 最后更新：old  \n| 消融实验 | 0 / 972 | old |\n")
    run = tmp_path / "run"
    run.mkdir()
    followup = tmp_path / "followup"
    followup.mkdir()
    recovery = tmp_path / "review-recovery"
    (recovery / "sessions" / "one").mkdir(parents=True)
    (recovery / "sessions" / "one" / "compiled.json").write_text("{}")
    (followup / "state.json").write_text(json.dumps({
        "status": "ablation_source_review_recovery_1",
        "effective_reviews": str(recovery),
    }))

    refresh(doc, run, followup)

    assert "来源盲审已汇总 1 / 969" in doc.read_text()


def test_ablation_progress_reports_adjudication_count(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text("> 最后更新：old  \n| 消融实验 | 0 / 972 | old |\n")
    run = tmp_path / "run"
    run.mkdir()
    followup = tmp_path / "followup"
    followup.mkdir()
    adjudication = tmp_path / "adjudication"
    (adjudication / "sessions" / "one").mkdir(parents=True)
    (adjudication / "sessions" / "one" / "compiled.json").write_text("{}")
    (followup / "state.json").write_text(json.dumps({
        "status": "invalid_review_correction_recovery_1",
        "review_resolution_coverage": 969,
        "review_adjudication_selected": 61,
        "effective_adjudication": str(adjudication),
    }))

    refresh(doc, run, followup)

    assert "来源覆盖 969 / 969，结构异常纠错已汇总 1 / 61" in doc.read_text()


def test_final_progress_keeps_holdout_locked_until_gate_opens(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text("| 最终冻结与留出门控 | 已启动 | old |\n| 留出集 | 锁定 | old |\n")
    gate = tmp_path / "gate"; gate.mkdir()
    (gate / "state.json").write_text(json.dumps({"completed": False, "holdout_opened": False,
                                                  "status": "waiting_for_admitted_ablation_analysis"}))
    refresh_final(doc, gate)
    text = doc.read_text()
    assert "不会提前读取留出题" in text
    assert "| 留出集 | 锁定 |" in text


def test_final_progress_reports_completed_holdout(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text("| 最终冻结与留出门控 | 已启动 | old |\n| 留出集 | 锁定 | old |\n")
    gate = tmp_path / "gate"; gate.mkdir()
    (gate / "state.json").write_text(json.dumps({"completed": True, "holdout_opened": True,
                                                  "status": "holdout_evaluation_complete"}))
    refresh_final(doc, gate)
    text = doc.read_text()
    assert "| 最终冻结与留出门控 | 已完成 |" in text
    assert "| 留出集 | 完成 |" in text


def test_final_progress_reports_holdout_answer_count(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text("| 最终冻结与留出门控 | 已启动 | old |\n| 留出集 | 锁定 | old |\n")
    gate = tmp_path / "gate"
    run = gate / "runs/final_holdout_flash_v1_baseline"
    write_json(run / "protocol.json", {"planned_sessions": 12})
    write_json(run / "GN/sessions/one/result.json", {})
    write_json(gate / "state.json", {"completed": False, "holdout_opened": True,
                                      "status": "running_baseline_holdout"})

    refresh_final(doc, gate)

    assert "留出终态 1 / 12（1 条回答、0 条冻结终止）" in doc.read_text()


def test_final_progress_counts_frozen_transport_terminal(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text("| 最终冻结与留出门控 | 已启动 | old |\n| 留出集 | 锁定 | old |\n")
    gate = tmp_path / "gate"
    run = gate / "runs/final_holdout_flash_v1_baseline"
    write_json(run / "protocol.json", {"planned_sessions": 2})
    write_json(run / "GN/sessions/failed/final.json", {
        "request_sha256": "x", "status": "transport_error",
        "events": [{"status": "transport_error"}] * 9,
    })
    write_json(gate / "state.json", {"completed": False, "holdout_opened": True,
                                      "status": "running_baseline_holdout"})

    refresh_final(doc, gate)

    assert "留出终态 1 / 2（0 条回答、1 条冻结终止）" in doc.read_text()


def test_final_progress_reports_holdout_review_count(tmp_path):
    doc = tmp_path / "progress.md"
    doc.write_text("| 最终冻结与留出门控 | 已启动 | old |\n| 留出集 | 锁定 | old |\n")
    gate = tmp_path / "gate"
    write_json(gate / "reviews/final_holdout_flash_v1_baseline/sessions/one/compiled.json", {})
    write_json(gate / "baseline-admission.json", {"answers": 12})
    write_json(gate / "state.json", {"completed": False, "holdout_opened": True,
                                      "status": "reviewing_baseline_holdout"})

    refresh_final(doc, gate)

    assert "留出来源盲审已汇总 1 / 12" in doc.read_text()
