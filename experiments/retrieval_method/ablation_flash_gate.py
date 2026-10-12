"""完整 Flash 候选准入后才预注册、冻结并执行真实消融。"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import time

import candidate_ablation as ablation
import leaderboard_admission as admission
import leaderboard_adjudication as adjudication
import leaderboard_audit as audit
import leaderboard_results as quality
from leaderboard_continue import run


def admitted_replay_checkpoint(root: Path, followup: Path, *, revalidate: bool = True) -> bool:
    """Return true only for a complete, protocol-bound replay admission."""
    try:
        protocol = audit.read(root / "protocol.json")
        checkpoint = audit.read(followup / "admission.json")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return False
    expected = protocol.get("planned_sessions")
    def valid(report: dict) -> bool:
        return bool(
            report.get("passed")
            and report.get("protocol_sha256") == audit.sha(root / "protocol.json")
            and report.get("expected") == expected
            and report.get("answers", 0) + report.get("terminal_failures", 0) == expected
            and report.get("replayed") == report.get("answers")
            and set(report.get("provider_models", {})) == {"deepseek-flash"}
            and not report.get("errors")
        )

    if not valid(checkpoint):
        return False
    if not revalidate:
        return True
    current = admission.check(root)
    audit.save(followup / "admission-resume-revalidated.json", current)
    return valid(current)


def compiled_review_count(review_root: Path) -> int:
    return sum(1 for _ in (review_root / "sessions").glob("*/compiled.json"))


def review_resolution_coverage(root: Path, review_root: Path) -> tuple[int, int]:
    compiled = {path.parent.name for path in (review_root / "sessions").glob("*/compiled.json")}
    selected = set(adjudication.selection(root, review_root))
    return len(compiled | selected), len(selected)


def missing_compiled_review_evidence(review_root: Path) -> list[str]:
    """Return compiled judgments whose accepted reviewer responses are absent."""
    missing = []
    for compiled_path in sorted((review_root / "sessions").glob("*/compiled.json")):
        compiled = audit.read(compiled_path)
        count = compiled.get("review_count")
        if type(count) is not int or count < 1:
            missing.append(compiled_path.parent.name)
            continue
        if any(not (compiled_path.parent / f"review-{index}.json").exists()
               for index in range(1, count + 1)):
            missing.append(compiled_path.parent.name)
    return missing


def next_recovery_path(base: Path, suffix: str) -> tuple[Path, int]:
    generation = 1
    while (base.parent / f"{base.name}_{suffix}_v{generation}").exists():
        generation += 1
    return base.parent / f"{base.name}_{suffix}_v{generation}", generation


def prepare_review_recovery(args, root: Path, base_reviews: Path, source: Path,
                            output: Path) -> tuple[Path, int]:
    """Freeze a fresh namespace and carry complete evidence for prior judgments."""
    target, generation = next_recovery_path(base_reviews, "recovery")
    code = run(
        [str(args.review_python), str(base_reviews / "leaderboard_review.py"), "prepare",
         "--run", str(root), "--output", str(target)],
        output, f"ablation-review-recovery-{generation}-prepare",
    )
    if code:
        raise RuntimeError("ablation review recovery freeze failed")
    if audit.sha(target / "protocol.json") != audit.sha(base_reviews / "protocol.json"):
        raise ValueError("review recovery changed the frozen review protocol")
    lineage = [source, base_reviews]
    lineage.extend(sorted(
        base_reviews.parent.glob(f"{base_reviews.name}_recovery_v*"),
        key=lambda path: int(path.name.rsplit("_v", 1)[1]),
        reverse=True,
    ))
    lineage = list(dict.fromkeys(lineage))
    copied = {}
    copied_responses = {}
    for compiled in sorted((source / "sessions").glob("*/compiled.json")):
        destination = target / "sessions" / compiled.parent.name / "compiled.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(compiled, destination)
        copied[compiled.parent.name] = audit.sha(destination)
        count = audit.read(compiled).get("review_count")
        origin = next((candidate / "sessions" / compiled.parent.name
                       for candidate in lineage
                       if (candidate / "sessions" / compiled.parent.name / "compiled.json").exists()
                       and audit.sha(candidate / "sessions" / compiled.parent.name / "compiled.json") == audit.sha(compiled)
                       and type(count) is int
                       and all((candidate / "sessions" / compiled.parent.name / f"review-{index}.json").exists()
                               for index in range(1, count + 1))), None)
        if origin is None:
            raise FileNotFoundError(f"compiled source review lacks response lineage: {compiled.parent.name}")
        for index in range(1, count + 1):
            response = origin / f"review-{index}.json"
            response_destination = destination.parent / response.name
            shutil.copy2(response, response_destination)
            copied_responses[f"{compiled.parent.name}/{response.name}"] = audit.sha(response_destination)
    copied_invalid = {}
    for blind_id in sorted(adjudication.selection(root, source)):
        if blind_id in copied:
            continue
        for response in sorted((source / "sessions" / blind_id).glob("review-*.json")):
            destination = target / "sessions" / blind_id / response.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(response, destination)
            copied_invalid[f"{blind_id}/{response.name}"] = audit.sha(destination)
    audit.save(
        target / "recovery-manifest.json",
        {
            "schema": "source-review-transport-recovery-v1",
            "source": str(source),
            "source_protocol_sha256": audit.sha(source / "protocol.json"),
            "target_protocol_sha256": audit.sha(target / "protocol.json"),
            "copied_compiled": copied,
            "copied_compiled_response_evidence": copied_responses,
            "copied_structurally_invalid_responses": copied_invalid,
            "policy": "carry completed judgments with their accepted response evidence; retry missing judgments in a fresh transport namespace",
        },
    )
    return target, generation


def prepare_adjudication_recovery(args, root: Path, reviews: Path, base: Path,
                                  prior: Path | None, generation: int, output: Path) -> Path:
    review_generation = reviews.name.rsplit("_v", 1)[-1]
    target = base.parent / f"{base.name}_for_review_recovery_v{review_generation}_g{generation}"
    if (target / "protocol.json").exists():
        return target
    command = [
        str(args.review_python), str(base / "leaderboard_adjudication.py"), "prepare",
        "--run", str(root), "--reviews", str(reviews), "--output", str(target),
    ]
    if prior is not None:
        command.extend(["--prior", str(prior)])
    code = run(command, output, f"ablation-adjudication-recovery-{generation}-prepare")
    if code:
        raise RuntimeError("ablation adjudication recovery freeze failed")
    protocol = audit.read(target / "protocol.json")
    if protocol.get("model") != "deepseek-flash" or Path(protocol["parent_reviews"]) != reviews:
        raise ValueError("adjudication recovery parent or model drift")
    return target


def resume_after_replay_admission(args, root: Path, reviews: Path, adjudications: Path,
                                  followup: Path, output: Path) -> dict:
    """Resume network-sensitive review stages without repeating admitted replay."""
    checkpoint = audit.read(followup / "admission.json")
    state = {
        "pid": os.getpid(),
        "completed": False,
        "terminal_sessions": checkpoint["expected"],
        "replay_admission_sha256": audit.sha(followup / "admission.json"),
    }

    def mark(status: str) -> None:
        state["status"] = status
        audit.save(followup / "state.json", state)
        print(status, flush=True)

    review_protocol = audit.read(reviews / "protocol.json")
    adjudication_protocol = audit.read(adjudications / "protocol.json")
    if review_protocol.get("model") != "deepseek-flash" or adjudication_protocol.get("model") != "deepseek-flash":
        raise ValueError("post-admission review must use exact deepseek-flash protocols")

    expected_reviews = checkpoint["answers"]
    effective_reviews = reviews
    existing = sorted(
        reviews.parent.glob(f"{reviews.name}_recovery_v*"),
        key=lambda path: int(path.name.rsplit("_v", 1)[1]),
    )
    if existing:
        effective_reviews = existing[-1]
    review_generation = 0
    for attempt in range(1, 101):
        if not (effective_reviews / "evaluation_only" / "blind-map.json").exists():
            state["effective_reviews"] = str(effective_reviews)
            mark(f"ablation_source_review_start_prepared_{effective_reviews.name}")
            code = run(
                [str(args.review_python), str(effective_reviews / "leaderboard_review.py"), "run",
                 "--run", str(root), "--output", str(effective_reviews),
                 "--key-file", str(args.key_file), "--workers", "2"],
                output, f"ablation-review-start-prepared-{attempt}",
            )
            if code not in {0, 75}:
                raise RuntimeError("prepared ablation review generation failed to start")
            if code == 75:
                mark("ablation_review_waiting_for_network_resume")
                time.sleep(30)
        coverage, selected = review_resolution_coverage(root, effective_reviews)
        missing_evidence = missing_compiled_review_evidence(effective_reviews)
        state.update(review_resolution_coverage=coverage, review_adjudication_selected=selected,
                     compiled_review_evidence_missing=len(missing_evidence))
        if coverage == expected_reviews and not missing_evidence:
            break
        effective_reviews, review_generation = prepare_review_recovery(
            args, root, reviews, effective_reviews, output,
        )
        state["effective_reviews"] = str(effective_reviews)
        mark(f"ablation_source_review_recovery_{review_generation}")
        code = run(
            [str(args.review_python), str(effective_reviews / "leaderboard_review.py"), "run",
             "--run", str(root), "--output", str(effective_reviews), "--key-file", str(args.key_file),
             "--workers", "2"],
            output, f"ablation-review-recovery-{review_generation}",
        )
        if code == 75:
            mark("ablation_review_waiting_for_network_resume")
            time.sleep(30)
            continue
        if code:
            raise RuntimeError("ablation source review resume failed")
        coverage, selected = review_resolution_coverage(root, effective_reviews)
        missing_evidence = missing_compiled_review_evidence(effective_reviews)
        state.update(review_resolution_coverage=coverage, review_adjudication_selected=selected,
                     compiled_review_evidence_missing=len(missing_evidence))
        if coverage != expected_reviews or missing_evidence:
            mark("ablation_source_review_missing_judgments")
    else:
        raise RuntimeError("ablation source review exceeded recovery generation limit")
    coverage, selected = review_resolution_coverage(root, effective_reviews)
    missing_evidence = missing_compiled_review_evidence(effective_reviews)
    state.update(review_resolution_coverage=coverage, review_adjudication_selected=selected,
                 compiled_review_evidence_missing=len(missing_evidence))
    if coverage != expected_reviews or missing_evidence:
        raise RuntimeError("ablation source review recovery remained incomplete")

    report = None
    prior = None
    effective_adjudication = adjudications
    for generation in range(1, 21):
        effective_adjudication = prepare_adjudication_recovery(
            args, root, effective_reviews, adjudications, prior, generation, output,
        )
        state["effective_adjudication"] = str(effective_adjudication)
        mark(f"invalid_review_correction_recovery_{generation}")
        code = run(
            [str(args.review_python), str(effective_adjudication / "leaderboard_adjudication.py"), "run",
             "--run", str(root), "--reviews", str(effective_reviews), "--output", str(effective_adjudication),
             "--key-file", str(args.key_file), "--workers", "2"],
            output, f"ablation-adjudication-recovery-{generation}",
        )
        if code == 75:
            mark("ablation_adjudication_waiting_for_network_resume")
            time.sleep(30)
            prior = effective_adjudication
            continue
        if code:
            raise RuntimeError("ablation source adjudication resume failed")
        report = quality.assemble(
            root, effective_reviews, followup / "quality.json", [effective_adjudication],
        )
        if report["all_arms_rankable"]:
            break
        prior = effective_adjudication
    if report is None:
        raise RuntimeError("ablation source adjudication produced no report")
    state.update(
        completed=bool(report["all_arms_rankable"]),
        all_arms_rankable=bool(report["all_arms_rankable"]),
        effective_reviews=str(effective_reviews),
        effective_adjudication=str(effective_adjudication),
        remaining="Analyze all registered effects, freeze final method, then open and evaluate holdout.",
    )
    mark("ablation_evaluation_complete" if state["completed"] else "ablation_source_reviews_unresolved")
    return state


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in [
        "candidate",
        "candidate-reviews",
        "candidate-adjudications",
        "candidate-followup",
        "ablation-run",
        "ablation-reviews",
        "ablation-adjudications",
        "ablation-followup",
        "analysis",
        "python",
        "review-python",
        "key-file",
        "output",
    ]:
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    with (output / "supervisor.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = {"pid": os.getpid(), "status": "starting", "completed": False}

        def mark(status: str) -> None:
            state["status"] = status
            audit.save(output / "state.json", state)
            print(status, flush=True)

        candidate = args.candidate.resolve()
        candidate_followup = args.candidate_followup.resolve()
        mark("waiting_for_full_candidate_admission")
        while True:
            try:
                parent = audit.read(candidate_followup / "state.json")
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(20)
                continue
            if parent.get("completed"):
                break
            pid = parent.get("pid")
            if pid and not Path("/proc", str(pid)).exists():
                mark("candidate_supervisor_stopped_before_completion")
                time.sleep(10)
                mark("waiting_for_full_candidate_admission")
                continue
            time.sleep(20)
        if not parent.get("all_arms_rankable"):
            mark("candidate_not_rankable")
            return

        mark("revalidating_full_candidate")
        candidate_report = output / "candidate-quality-revalidated.json"
        protocol = audit.verify(candidate)
        preregistration = output / "preregistration.json"
        if preregistration.exists():
            registration = audit.read(preregistration)
            report = audit.read(candidate_report)
            if audit.sha(candidate_report) != registration.get("candidate_quality_sha256"):
                raise ValueError("preserved preregistration candidate report drift")
        else:
            report = quality.assemble(
                candidate,
                args.candidate_reviews.resolve(),
                candidate_report,
                [args.candidate_adjudications.resolve()],
            )
            registration = {
                "schema": "candidate-flash-post-result-ablation-preregistration-v1",
                "created_unix_ns": time.time_ns(),
                "model": "deepseek-flash",
                "source_candidate_protocol_sha256": audit.sha(candidate / "protocol.json"),
                "candidate_quality_sha256": audit.sha(candidate_report),
                "candidate_result_observed_before_registration": True,
                "candidate_result_used_only_as_frozen_reference": True,
                "planned_additional_arms": len(ablation.ARM_FACTORS),
                "planned_additional_sessions": 972,
                "arm_factors": {key: list(value) for key, value in ablation.ARM_FACTORS.items()},
                "primary_estimand": "18-family paired strict-success difference: full candidate minus each single-factor removal",
                "registered_interactions": [
                    "role_scope x conditional_bilateral",
                    "paths x evidence_groups",
                ],
                "multiple_comparison_scope": "Report every registered effect and pointwise interval; do not select only favorable effects or claim family-wise significance.",
                "holdout_unlocked": False,
            }
            audit.save(preregistration, registration)
        if (
            protocol["model"] != "deepseek-flash"
            or not report["all_arms_rankable"]
            or registration.get("source_candidate_protocol_sha256") != audit.sha(candidate / "protocol.json")
            or registration.get("arm_factors") != {key: list(value) for key, value in ablation.ARM_FACTORS.items()}
        ):
            raise ValueError("exact Flash candidate admission or preserved preregistration failed")
        state["preregistration_sha256"] = audit.sha(preregistration)

        ablation_run = args.ablation_run.resolve()
        mark("preparing_frozen_ablation_grid")
        if not (ablation_run / "protocol.json").exists():
            if ablation_run.exists():
                raise FileExistsError("incomplete ablation preparation requires audit")
            code = run(
                [
                    str(args.python),
                    str(Path(__file__).with_name("candidate_ablation.py")),
                    "prepare",
                    "--run",
                    str(ablation_run),
                    "--parent",
                    str(candidate),
                    "--candidate-report",
                    str(candidate_report),
                    "--preregistration",
                    str(preregistration),
                ],
                output,
                "ablation-prepare",
            )
            if code:
                raise RuntimeError("ablation preparation failed")
        audit.verify(ablation_run)
        for command in ("verify", "smoke"):
            mark(f"ablation_{command}")
            code = run(
                [str(args.python), str(ablation_run / "candidate_ablation.py"), command, "--run", str(ablation_run)],
                output,
                f"ablation-{command}",
            )
            if code:
                raise RuntimeError(f"ablation {command} failed")

        ablation_reviews = args.ablation_reviews.resolve()
        mark("freezing_ablation_source_review")
        if not (ablation_reviews / "protocol.json").exists():
            if ablation_reviews.exists():
                raise FileExistsError("incomplete ablation source review freeze requires audit")
            code = run(
                [
                    str(args.review_python),
                    str(Path(__file__).with_name("leaderboard_review.py")),
                    "prepare",
                    "--run",
                    str(ablation_run),
                    "--output",
                    str(ablation_reviews),
                ],
                output,
                "ablation-review-prepare",
            )
            if code:
                raise RuntimeError("ablation review freeze failed")

        ablation_adjudications = args.ablation_adjudications.resolve()
        mark("freezing_ablation_source_adjudication")
        if not (ablation_adjudications / "protocol.json").exists():
            if ablation_adjudications.exists():
                raise FileExistsError("incomplete ablation adjudication freeze requires audit")
            code = run(
                [
                    str(args.review_python),
                    str(Path(__file__).with_name("leaderboard_adjudication.py")),
                    "prepare",
                    "--run",
                    str(ablation_run),
                    "--reviews",
                    str(ablation_reviews),
                    "--output",
                    str(ablation_adjudications),
                ],
                output,
                "ablation-adjudication-prepare",
            )
            if code:
                raise RuntimeError("ablation adjudication freeze failed")

        followup = args.ablation_followup.resolve()
        if admitted_replay_checkpoint(ablation_run, followup):
            mark("resuming_ablation_after_replay_admission")
            result_state = resume_after_replay_admission(
                args, ablation_run, ablation_reviews, ablation_adjudications, followup, output,
            )
        else:
            mark("running_preregistered_ablation_followup")
            while True:
                code = run(
                    [
                        str(args.python),
                        str(ablation_run / "ablation_followup.py"),
                        "--run",
                        str(ablation_run),
                        "--python",
                        str(args.python),
                        "--review-python",
                        str(args.review_python),
                        "--key-file",
                        str(args.key_file),
                        "--reviews",
                        str(ablation_reviews),
                        "--adjudications",
                        str(ablation_adjudications),
                        "--output",
                        str(followup),
                    ],
                    output,
                    "ablation-followup",
                )
                if code:
                    raise RuntimeError("ablation followup process failed")
                result_state = audit.read(followup / "state.json")
                if result_state.get("all_arms_rankable"):
                    break
                if result_state.get("status") in {
                    "ablation_waiting_for_network_resume",
                    "ablation_review_waiting_for_network_resume",
                    "ablation_adjudication_waiting_for_network_resume",
                }:
                    mark("ablation_followup_waiting_for_network_resume")
                    time.sleep(10)
                    continue
                mark("ablation_not_rankable")
                return
        if not result_state.get("all_arms_rankable"):
            mark("ablation_not_rankable")
            return

        mark("analyzing_all_registered_effects")
        effective_reviews = Path(result_state.get("effective_reviews", str(ablation_reviews)))
        effective_adjudication = Path(result_state.get("effective_adjudication", str(ablation_adjudications)))
        code = run(
            [
                str(args.python),
                str(ablation_run / "ablation_results.py"),
                "--reference-run",
                str(candidate),
                "--reference-reviews",
                str(args.candidate_reviews.resolve()),
                "--reference-adjudications",
                str(args.candidate_adjudications.resolve()),
                "--ablation-run",
                str(ablation_run),
                "--ablation-reviews",
                str(effective_reviews),
                "--ablation-adjudications",
                str(effective_adjudication),
                "--output",
                str(args.analysis.resolve()),
            ],
            output,
            "ablation-analysis",
        )
        if code:
            raise RuntimeError("ablation analysis failed")
        state.update(completed=True, all_arms_rankable=True,
                     remaining="Freeze the final method from all development evidence before opening holdout.")
        mark("ablation_analysis_complete")


if __name__ == "__main__":
    main()
