"""Wait for admitted ablations, freeze the final method, then run the unopened holdout."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import leaderboard_admission as admission
import leaderboard_adjudication as adjudication
import leaderboard_audit as audit
import leaderboard_results as quality


def absolute_executable(path: Path) -> Path:
    """Make a launcher absolute without dereferencing a virtualenv symlink."""
    return Path(os.path.abspath(path))


def save_state(output: Path, state, status):
    state["status"] = status
    audit.save(output / "state.json", state)
    print(status, flush=True)


def call(command, output: Path, label: str):
    with (output / (label + ".log")).open("a") as log:
        return subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                              env={**os.environ, "PYTHONHASHSEED": "0"}).returncode


def terminal_grid(root: Path):
    protocol = audit.verify(root)
    anchor = next(iter(protocol["groups"]))
    questions = audit.read(root / anchor / "questions.json")
    count = 0
    for arm, methods in protocol["groups"].items():
        for method in methods:
            for question in questions:
                for replicate in range(1, protocol["replicates"] + 1):
                    folder = root / arm / "sessions" / f"{question['id']}--{method}--r{replicate}"
                    if (folder / "result.json").exists() or quality.terminal_failure(folder):
                        count += 1
    return count, protocol["planned_sessions"]


def run_until_terminal(python: Path, root: Path, key: Path, output: Path, label: str):
    for attempt in range(1, 101):
        complete, planned = terminal_grid(root)
        if complete == planned:
            return
        code = call([str(python), str(root / "runner.py"), "run", "--run", str(root),
                     "--key-file", str(key), "--workers", "4"], output,
                    f"{label}-run-{attempt}")
        if code not in (0, 75):
            raise RuntimeError(f"{label} holdout runner failed with {code}")
        if code == 75:
            time.sleep(10)
    raise RuntimeError(f"{label} holdout did not reach its frozen terminal grid")


def replay_and_admit(python: Path, root: Path, output: Path, label: str):
    call([str(python), str(root / "runner.py"), "replay", "--run", str(root),
          "--workers", "4"], output, f"{label}-replay-parallel")
    result = admission.check(root)
    if not result["passed"]:
        call([str(python), str(root / "runner.py"), "replay", "--run", str(root),
              "--workers", "1"], output, f"{label}-replay-serial")
        result = admission.check(root)
    audit.save(output / f"{label}-admission.json", result)
    if not result["passed"]:
        raise RuntimeError(f"{label} holdout replay admission failed")


def review_coverage(root: Path, reviews: Path) -> tuple[int, int]:
    compiled = {path.parent.name for path in (reviews / "sessions").glob("*/compiled.json")}
    selected = set(adjudication.selection(root, reviews))
    return len(compiled | selected), len(selected)


def missing_review_evidence(reviews: Path) -> list[str]:
    missing = []
    for path in sorted((reviews / "sessions").glob("*/compiled.json")):
        count = audit.read(path).get("review_count")
        if type(count) is not int or count < 1 or any(
                not (path.parent / f"review-{index}.json").exists()
                for index in range(1, count + 1)):
            missing.append(path.parent.name)
    return missing


def prepare_review_recovery(review_python: Path, root: Path, base: Path, source: Path,
                            output: Path, label: str, generation: int) -> Path:
    target = base.parent / f"{base.name}-recovery-v{generation}"
    if (target / "protocol.json").exists():
        return target
    code = call([str(review_python), str(base / "leaderboard_review.py"), "prepare",
                 "--run", str(root), "--output", str(target)], output,
                f"{label}-review-recovery-{generation}-prepare")
    if code:
        raise RuntimeError("holdout source review recovery freeze failed")
    if audit.sha(target / "protocol.json") != audit.sha(base / "protocol.json"):
        raise ValueError("holdout review recovery changed the frozen protocol")
    copied_compiled = {}
    copied_responses = {}
    for compiled in sorted((source / "sessions").glob("*/compiled.json")):
        count = audit.read(compiled).get("review_count")
        if type(count) is not int or count < 1:
            raise ValueError("compiled holdout review has invalid response count")
        destination = target / "sessions" / compiled.parent.name
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(compiled, destination / "compiled.json")
        copied_compiled[compiled.parent.name] = audit.sha(destination / "compiled.json")
        for index in range(1, count + 1):
            response = compiled.parent / f"review-{index}.json"
            if not response.exists():
                raise FileNotFoundError(f"compiled holdout review lacks response: {compiled.parent.name}")
            shutil.copy2(response, destination / response.name)
            copied_responses[f"{compiled.parent.name}/{response.name}"] = audit.sha(destination / response.name)
    copied_invalid = {}
    for blind_id in sorted(adjudication.selection(root, source)):
        if blind_id in copied_compiled:
            continue
        destination = target / "sessions" / blind_id
        for response in sorted((source / "sessions" / blind_id).glob("review-*.json")):
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(response, destination / response.name)
            copied_invalid[f"{blind_id}/{response.name}"] = audit.sha(destination / response.name)
    audit.save(target / "recovery-manifest.json", {
        "schema": "holdout-source-review-transport-recovery-v1",
        "source": str(source),
        "source_protocol_sha256": audit.sha(source / "protocol.json"),
        "target_protocol_sha256": audit.sha(target / "protocol.json"),
        "copied_compiled": copied_compiled,
        "copied_compiled_response_evidence": copied_responses,
        "copied_structurally_invalid_responses": copied_invalid,
    })
    return target


def review_until_rankable(review_python: Path, root: Path, reviews: Path,
                          adjudications: Path, key: Path, output: Path, label: str):
    source = Path(__file__).with_name("leaderboard_review.py")
    if not (reviews / "protocol.json").exists():
        code = call([str(review_python), str(source), "prepare", "--run", str(root),
                     "--output", str(reviews)], output, f"{label}-review-prepare")
        if code:
            raise RuntimeError("holdout review freeze failed")
    admitted = admission.check(root)
    if not admitted["passed"]:
        raise RuntimeError(f"{label} holdout lost replay admission before review")
    expected = admitted["answers"]
    existing = sorted(reviews.parent.glob(f"{reviews.name}-recovery-v*"),
                      key=lambda path: int(path.name.rsplit("-v", 1)[1]))
    effective_reviews = existing[-1] if existing else reviews
    for generation in range(0, 100):
        code = call([str(review_python), str(effective_reviews / "leaderboard_review.py"), "run",
                     "--run", str(root), "--output", str(effective_reviews), "--key-file", str(key),
                     "--workers", "2"], output, f"{label}-review-{generation + 1}")
        if code not in (0, 75):
            raise RuntimeError(f"{label} holdout source review failed")
        coverage, _ = review_coverage(root, effective_reviews)
        if coverage == expected and not missing_review_evidence(effective_reviews):
            break
        effective_reviews = prepare_review_recovery(
            review_python, root, reviews, effective_reviews, output, label, generation + 1)
        if code == 75:
            time.sleep(10)
    else:
        raise RuntimeError(f"{label} holdout source review did not reach complete coverage")
    chains = []
    prior = None
    for generation in range(1, 21):
        current = adjudications.parent / f"{adjudications.name}-for-{effective_reviews.name}-v{generation}"
        if not (current / "protocol.json").exists():
            command = [str(review_python), str(Path(__file__).with_name("leaderboard_adjudication.py")),
                       "prepare", "--run", str(root), "--reviews", str(effective_reviews),
                       "--output", str(current)]
            if prior:
                command.extend(["--prior", str(prior)])
            code = call(command, output, f"{label}-adjudication-{generation}-prepare")
            if code:
                raise RuntimeError("holdout adjudication freeze failed")
        code = call([str(review_python), str(current / "leaderboard_adjudication.py"), "run",
                     "--run", str(root), "--reviews", str(effective_reviews), "--output", str(current),
                     "--key-file", str(key), "--workers", "2"], output,
                    f"{label}-adjudication-{generation}")
        if code not in (0, 75):
            raise RuntimeError("holdout adjudication runner failed")
        chains.append(current)
        report = quality.assemble(root, effective_reviews, output / f"{label}-quality.json", chains)
        if code == 0 and report["all_arms_rankable"]:
            audit.audit(root, output / f"{label}-cost-and-grid.json")
            return report, chains, effective_reviews
        prior = current
        if code == 75:
            time.sleep(10)
    raise RuntimeError(f"{label} holdout source judgments remain unresolved")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("ablation-gate", "ablation-run", "ablation-analysis", "selection-registration",
                 "baseline-run", "baseline-quality", "baseline-cost", "candidate-run",
                 "candidate-quality", "candidate-cost", "dataset", "baseline-python",
                 "candidate-python", "review-python", "key-file", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    state = {"pid": os.getpid(), "completed": False, "holdout_opened": False}
    while True:
        ablation_state = audit.read(args.ablation_gate.resolve() / "state.json")
        if ablation_state.get("completed") and ablation_state.get("all_arms_rankable"):
            break
        save_state(output, state, "waiting_for_admitted_ablation_analysis")
        time.sleep(15)

    analysis = args.ablation_analysis.resolve()
    if not (analysis / "ablation-quality.json").exists():
        raise RuntimeError("ablation gate claimed completion without quality analysis")
    audit.audit(args.ablation_run.resolve(), analysis / "ablation-cost-and-grid.json")
    code = call([str(args.candidate_python), str(Path(__file__).with_name("ablation_operational_sensitivity.py")),
                 "--reference-quality", str(args.candidate_quality),
                 "--ablation-quality", str(analysis / "ablation-quality.json"),
                 "--output", str(analysis / "terminal-transport-sensitivity.json")],
                output, "ablation-transport-sensitivity")
    if code:
        raise RuntimeError("ablation transport sensitivity analysis failed")
    freeze = output / "final-method-freeze-v1"
    if not (freeze / "implementation-gate.json").exists():
        save_state(output, state, "applying_preregistered_final_selection")
        code = call([
            str(args.candidate_python), str(Path(__file__).with_name("final_method_selection.py")),
            "--registration", str(args.selection_registration),
            "--baseline-quality", str(args.baseline_quality), "--baseline-cost", str(args.baseline_cost),
            "--candidate-quality", str(args.candidate_quality), "--candidate-cost", str(args.candidate_cost),
            "--ablation-quality", str(analysis / "ablation-quality.json"),
            "--ablation-cost", str(analysis / "ablation-cost-and-grid.json"),
            "--baseline-run", str(args.baseline_run), "--candidate-run", str(args.candidate_run),
            "--ablation-run", str(args.ablation_run), "--output", str(freeze),
        ], output, "final-selection")
        if code:
            raise RuntimeError("preregistered final selection failed")
    gate = audit.read(freeze / "implementation-gate.json")
    state["selected"] = gate["selected"]
    state["holdout_opened"] = True
    cohorts = [("baseline", absolute_executable(args.baseline_python))]
    if gate["selected"]["source"] != "baseline":
        cohorts.append(("candidate", absolute_executable(args.candidate_python)))
    completed = []
    for kind, python in cohorts:
        run = output / "runs" / f"final_holdout_flash_v1_{kind}"
        reviews = output / "reviews" / f"final_holdout_flash_v1_{kind}"
        adjudications = output / "reviews" / f"final_holdout_flash_source_{kind}"
        if not (run / "protocol.json").exists():
            save_state(output, state, f"preparing_{kind}_holdout")
            code = call([str(python), str(Path(__file__).with_name("final_holdout.py")), "prepare",
                         "--run", str(run), "--kind", kind, "--gate", str(freeze / "implementation-gate.json"),
                         "--dataset", str(args.dataset)], output, f"{kind}-prepare")
            if code:
                raise RuntimeError(f"{kind} holdout preparation failed")
        save_state(output, state, f"running_{kind}_holdout")
        run_until_terminal(python, run, args.key_file.resolve(), output, kind)
        save_state(output, state, f"replaying_{kind}_holdout")
        replay_and_admit(python, run, output, kind)
        save_state(output, state, f"reviewing_{kind}_holdout")
        report, chains, effective_reviews = review_until_rankable(
            absolute_executable(args.review_python), run, reviews, adjudications,
            args.key_file.resolve(), output, kind)
        completed.append({"kind": kind, "run": str(run), "reviews": str(effective_reviews),
                          "adjudications": [str(path) for path in chains],
                          "quality_sha256": audit.sha(output / f"{kind}-quality.json"),
                          "cost_sha256": audit.sha(output / f"{kind}-cost-and-grid.json")})
    state.update(completed=True, cohorts=completed)
    save_state(output, state, "holdout_evaluation_complete")
    results = output / "results"
    code = call([str(args.candidate_python), str(Path(__file__).with_name("final_holdout_results.py")),
                 "--evaluation", str(output), "--output", str(results)], output, "final-holdout-results")
    if code:
        state["completed"] = False
        save_state(output, state, "holdout_result_compilation_failed")
        raise RuntimeError("final holdout result compilation failed")
    state["final_results_sha256"] = audit.sha(results / "final-holdout-results.json")
    prices = output.parent / "deepseek-flash-prices-20260910.json"
    for name, root in (("development", output.parent), ("holdout", output)):
        cost_path = results / f"{name}-complete-cost.json"
        code = call([str(args.candidate_python), str(Path(__file__).with_name("leaderboard_cost.py")),
                     "--root", str(root), "--prices", str(prices), "--output", str(cost_path)],
                    output, f"{name}-complete-cost")
        if code:
            raise RuntimeError(f"{name} complete cost reconstruction failed")
        state[f"{name}_complete_cost_sha256"] = audit.sha(cost_path)
    cost_report = results / "cost-report"
    code = call([str(args.candidate_python), str(Path(__file__).with_name("final_cost_report.py")),
                 "--development-ledger", str(results / "development-complete-cost.json"),
                 "--holdout-ledger", str(results / "holdout-complete-cost.json"),
                 "--baseline-cost", str(args.baseline_cost), "--candidate-cost", str(args.candidate_cost),
                 "--ablation-cost", str(analysis / "ablation-cost-and-grid.json"),
                 "--holdout-results", str(results / "final-holdout-results.json"),
                 "--output", str(cost_report)], output, "final-cost-report")
    if code:
        raise RuntimeError("final human-readable cost report failed")
    state["final_cost_summary_sha256"] = audit.sha(cost_report / "final-cost-summary.json")
    save_state(output, state, "holdout_evaluation_complete")


if __name__ == "__main__":
    main()
