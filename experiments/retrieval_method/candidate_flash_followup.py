"""基线全量准入后，续跑已冻结 Flash 候选、回放、来源评审与仲裁。"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import time

import leaderboard_admission as admission
import leaderboard_audit as audit
import leaderboard_results as quality
from leaderboard_continue import run, wait_unlocked


def complete_grid(root: Path, protocol: dict) -> bool:
    questions = audit.read(root / "control/questions.json")
    folders = [
        root / group / "sessions" / f"{question['id']}--{method}--r{replicate}"
        for group, methods in protocol["groups"].items()
        for method in methods
        for question in questions
        for replicate in range(1, protocol["replicates"] + 1)
    ]
    return all((folder / "result.json").exists() or quality.terminal_failure(folder) for folder in folders)


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in [
        "baseline",
        "baseline-reviews",
        "baseline-followup",
        "candidate",
        "candidate-reviews",
        "candidate-adjudications",
        "python",
        "key-file",
        "output",
    ]:
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--baseline-adjudications", type=Path, action="append", required=True)
    args = cli.parse_args()

    baseline = args.baseline.resolve()
    baseline_reviews = args.baseline_reviews.resolve()
    candidate = args.candidate.resolve()
    candidate_reviews = args.candidate_reviews.resolve()
    candidate_adjudications = args.candidate_adjudications.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    with (output / "supervisor.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = {"pid": os.getpid(), "status": "starting", "completed": False}

        def mark(stage: str) -> None:
            state["status"] = stage
            audit.save(output / "state.json", state)
            print(stage, flush=True)

        def run_with_network_resume(command: list[str], label: str, stage: str) -> int:
            resume = 0
            while True:
                code = run(command, output, label)
                if code != 75:
                    return code
                resume += 1
                state["last_exit_code"] = code
                state["network_resumes"] = state.get("network_resumes", 0) + 1
                mark(stage + "_waiting_for_network_resume")
                time.sleep(10)
                mark(stage + f"_network_resume_{resume}")

        mark("waiting_for_baseline_admission")
        while True:
            try:
                parent = audit.read(args.baseline_followup.resolve() / "state.json")
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(20)
                continue
            if parent.get("completed"):
                break
            pid = parent.get("pid")
            if pid and not Path("/proc", str(pid)).exists():
                mark("baseline_supervisor_stopped_before_completion")
                time.sleep(10)
                mark("waiting_for_baseline_admission")
                continue
            time.sleep(20)

        mark("revalidating_baseline_admission")
        baseline_report = output / "baseline-admission-quality.json"
        report = quality.assemble(
            baseline,
            baseline_reviews,
            baseline_report,
            [path.resolve() for path in args.baseline_adjudications],
        )
        if not report["all_arms_rankable"]:
            state["all_arms_rankable"] = False
            mark("baseline_not_rankable")
            return

        protocol = audit.verify(candidate)
        if protocol["model"] != "deepseek-flash":
            raise ValueError("candidate model must be deepseek-flash")
        if protocol["parent_protocol_sha256"] != report["protocol_sha256"]:
            raise ValueError("candidate baseline protocol drift")
        state["baseline_quality_sha256"] = audit.sha(baseline_report)

        wait_unlocked(candidate)
        for attempt in range(1, 4):
            mark(f"candidate_full_development_run_{attempt}")
            code = run_with_network_resume(
                [
                    str(args.python),
                    str(candidate / "candidate_runner.py"),
                    "run",
                    "--run",
                    str(candidate),
                    "--baseline-report",
                    str(baseline_report),
                    "--key-file",
                    str(args.key_file),
                    "--workers",
                    "4",
                ],
                f"candidate-run-{attempt}",
                "candidate",
            )
            if code:
                state["last_exit_code"] = code
                mark("candidate_waiting_for_network_resume" if code == 75 else "candidate_runner_failed")
                return
            if complete_grid(candidate, protocol):
                break

        if not admission.check(candidate)["passed"]:
            mark("candidate_zero_model_replay")
            wait_unlocked(candidate)
            run(
                [str(args.python), str(candidate / "candidate_runner.py"), "replay", "--run", str(candidate), "--workers", "4"],
                output,
                "candidate-replay",
            )
        else:
            mark("candidate_replay_admission_reused")
        if not admission.check(candidate)["passed"]:
            state["all_arms_rankable"] = False
            mark("candidate_replay_or_budget_admission_failed")
            return

        wait_unlocked(candidate_reviews)
        for attempt in range(1, 4):
            mark(f"candidate_source_review_{attempt}")
            code = run_with_network_resume(
                [
                    str(args.python),
                    str(candidate_reviews / "leaderboard_review.py"),
                    "run",
                    "--run",
                    str(candidate),
                    "--output",
                    str(candidate_reviews),
                    "--key-file",
                    str(args.key_file),
                    "--workers",
                    "2",
                ],
                f"candidate-review-{attempt}",
                "candidate_review",
            )
            if code:
                state["last_exit_code"] = code
                mark("candidate_review_waiting_for_network_resume" if code == 75 else "candidate_review_failed")
                return

        wait_unlocked(candidate_adjudications)
        for attempt in range(1, 4):
            mark(f"candidate_source_adjudication_{attempt}")
            code = run_with_network_resume(
                [
                    str(args.python),
                    str(candidate_adjudications / "leaderboard_adjudication.py"),
                    "run",
                    "--run",
                    str(candidate),
                    "--reviews",
                    str(candidate_reviews),
                    "--output",
                    str(candidate_adjudications),
                    "--key-file",
                    str(args.key_file),
                    "--workers",
                    "2",
                ],
                f"candidate-adjudication-{attempt}",
                "candidate_adjudication",
            )
            if code:
                state["last_exit_code"] = code
                mark("candidate_adjudication_waiting_for_network_resume" if code == 75 else "candidate_adjudication_failed")
                return

        mark("candidate_quality_report")
        result = quality.assemble(
            candidate,
            candidate_reviews,
            output / "candidate-quality.json",
            [candidate_adjudications],
        )
        audit.audit(candidate, output / "candidate-cost-and-grid.json")
        state.update(
            completed=True,
            all_arms_rankable=result["all_arms_rankable"],
            remaining=(
                "Preregister and run the true ablations only after this full candidate is rankable; "
                "freeze the selected method before opening holdout."
            ),
        )
        mark("candidate_development_finished" if result["all_arms_rankable"] else "candidate_source_reviews_unresolved")


if __name__ == "__main__":
    main()
