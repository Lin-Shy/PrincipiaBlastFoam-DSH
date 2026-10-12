"""Atomically refresh the human-readable Chapter 2 progress document."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time


STATUS_TEXT = {
    "ablation_run": "真实回答正在运行",
    "ablation_waiting_for_network_resume": "网络熔断，按冻结协议自动续跑",
    "ablation_zero_model_replay": "回答完成，正在零模型重放",
    "ablation_source_review": "重放通过，正在来源盲审",
    "invalid_review_correction": "正在纠正无效来源评审",
    "ablation_adjudication_waiting_for_network_resume": "来源仲裁网络熔断，正在自动续跑",
    "ablation_evaluation_complete": "回答、重放、评审和准入全部完成",
}


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def describe(status: str) -> str:
    for prefix, text in STATUS_TEXT.items():
        if status.startswith(prefix):
            return text
    return status or "等待监督状态"


def completed_log_entries(path: Path) -> tuple[int, int]:
    """Count terminal subprocess records without inspecting experiment content."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return 0, 0
    return sum(line.startswith("DONE ") for line in lines), sum(line.startswith("ERROR ") for line in lines)


def terminal_answer_failures(run: Path) -> int:
    count = 0
    for session in run.glob("*/sessions/*"):
        if (session / "result.json").exists():
            continue
        for path in session.glob("*.json"):
            record = read_json(path)
            if "request_sha256" not in record or record.get("status") == "response":
                continue
            events = record.get("events", [])
            if record.get("status") == "invalid_response" or (
                    record.get("status") == "transport_error" and (
                        len(events) >= 9 or any(event.get("http_status") in (400, 401, 402, 403)
                                                for event in events))):
                count += 1
                break
    return count


def refresh(doc: Path, run: Path, followup: Path) -> int:
    count = sum(1 for _ in run.glob("*/sessions/*/result.json"))
    followup_state = read_json(followup / "state.json")
    raw_status = str(followup_state.get("status", ""))
    status = describe(raw_status)
    if raw_status.startswith("ablation_zero_model_replay"):
        done, errors = completed_log_entries(followup / "replay-parallel.log")
        status = f"回答完成，零模型重放 {done + errors} / 972（{errors} 个预期或异常终止项）"
    elif raw_status.startswith("ablation_source_review"):
        effective_reviews = Path(followup_state.get(
            "effective_reviews",
            followup.parent / "reviews" / "candidate_ablation_flash_v1",
        ))
        reviewed = sum(
            1 for _ in (effective_reviews / "sessions").glob("*/compiled.json")
        )
        status = f"重放通过，来源盲审已汇总 {reviewed} / 969"
    elif raw_status.startswith("invalid_review_correction"):
        selected = int(followup_state.get("review_adjudication_selected", 0))
        adjudication = Path(followup_state.get("effective_adjudication", ""))
        corrected = (sum(1 for _ in (adjudication / "sessions").glob("*/compiled.json"))
                     if str(adjudication) else 0)
        coverage = int(followup_state.get("review_resolution_coverage", 0))
        status = (f"来源覆盖 {coverage} / 969，结构异常纠错已汇总 "
                  f"{corrected} / {selected}")
    content = doc.read_text()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    content, first = re.subn(r"(?m)^> 最后更新：.*?  $", f"> 最后更新：{stamp}  ", content, count=1)
    content, second = re.subn(
        r"(?m)^\| 消融实验 \| \d+ / 972 \|.*$",
        f"| 消融实验 | {count} / 972 | {status} |",
        content,
        count=1,
    )
    if first != 1 or second != 1:
        raise ValueError("progress document markers changed")
    temporary = doc.with_suffix(doc.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(doc)
    return count


def refresh_final(doc: Path, gate_path: Path) -> None:
    state = read_json(gate_path / "state.json")
    status = str(state.get("status", "waiting_for_admitted_ablation_analysis"))
    labels = {
        "waiting_for_admitted_ablation_analysis": "等待消融全部准入；不会提前读取留出题",
        "applying_preregistered_final_selection": "正在按预注册规则冻结最终方法",
        "holdout_evaluation_complete": "最终方法与留出评测已完成",
        "holdout_result_compilation_failed": "留出结果汇总失败，保留原始证据待修复",
    }
    if status.startswith("preparing_"):
        final_text = "最终方法已冻结，正在准备留出队列"
    elif status.startswith("running_"):
        kind = status.removeprefix("running_").removesuffix("_holdout")
        run = gate_path / "runs" / f"final_holdout_flash_v1_{kind}"
        protocol = read_json(run / "protocol.json")
        planned = int(protocol.get("planned_sessions", 0))
        answers = sum(1 for _ in run.glob("*/sessions/*/result.json"))
        failures = terminal_answer_failures(run)
        final_text = (f"最终方法已冻结，留出终态 {answers + failures} / {planned or '未知'}"
                      f"（{answers} 条回答、{failures} 条冻结终止）")
    elif status.startswith("replaying_"):
        kind = status.removeprefix("replaying_").removesuffix("_holdout")
        done, errors = completed_log_entries(gate_path / f"{kind}-replay-parallel.log")
        final_text = f"最终方法已冻结，留出重放已处理 {done + errors} 条"
    elif status.startswith("reviewing_"):
        kind = status.removeprefix("reviewing_").removesuffix("_holdout")
        base = gate_path / "reviews" / f"final_holdout_flash_v1_{kind}"
        recoveries = sorted(base.parent.glob(f"{base.name}-recovery-v*"),
                            key=lambda path: int(path.name.rsplit("-v", 1)[1]))
        reviews = recoveries[-1] if recoveries else base
        reviewed = sum(1 for _ in (reviews / "sessions").glob("*/compiled.json"))
        admitted = read_json(gate_path / f"{kind}-admission.json")
        expected = admitted.get("answers", "未知")
        final_text = f"最终方法已冻结，留出来源盲审已汇总 {reviewed} / {expected}"
    else:
        final_text = labels.get(status, status)
    opened = bool(state.get("holdout_opened"))
    completed = bool(state.get("completed")) and status == "holdout_evaluation_complete"
    holdout_progress = "完成" if completed else "已开启" if opened else "锁定"
    holdout_text = ("回答、重放、评审、成本与汇总全部完成" if completed else
                    "最终方法已冻结，正在执行" if opened else "仅在最终方法冻结后开启")
    content = doc.read_text()
    content, first = re.subn(
        r"(?m)^\| 最终冻结与留出门控 \|.*$",
        f"| 最终冻结与留出门控 | {'已完成' if completed else '已启动'} | {final_text} |",
        content, count=1)
    content, second = re.subn(
        r"(?m)^\| 留出集 \|.*$",
        f"| 留出集 | {holdout_progress} | {holdout_text} |",
        content, count=1)
    if first != 1 or second != 1:
        raise ValueError("final progress document markers changed")
    temporary = doc.with_suffix(doc.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(doc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--followup", type=Path, required=True)
    parser.add_argument("--final-gate", type=Path)
    parser.add_argument("--interval", type=int, default=0)
    args = parser.parse_args()
    while True:
        refresh(args.doc, args.run, args.followup)
        if args.final_gate:
            refresh_final(args.doc, args.final_gate)
        state = read_json(args.followup / "state.json")
        final_done = not args.final_gate or read_json(args.final_gate / "state.json").get("completed")
        if not args.interval or (state.get("completed") and final_done):
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
