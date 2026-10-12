"""对已完成盲审的开发集质量汇总做确定性逐事实族误差分析。"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


METRICS = (
    "qa_success",
    "answer_accuracy",
    "citation_accuracy",
    "required_evidence_recall",
    "cross_source_completeness",
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _average(sessions: list[dict], metric: str) -> float | None:
    values = [session["quality"].get(metric) for session in sessions]
    applicable = [value for value in values if value is not None]
    return mean(applicable) if applicable else None


def _failure_bucket(session: dict) -> str:
    quality = session["quality"]
    if quality["qa_success"]:
        return "strict_success"
    answer_accuracy = quality.get("answer_accuracy")
    if answer_accuracy == 1:
        return "content_complete_but_strict_support_failed"
    if isinstance(answer_accuracy, (int, float)) and answer_accuracy > 0:
        return "partial_content"
    return "zero_content_or_empty_answer"


def analyse(
    quality_path: Path,
    candidate_arm: str = "principia_index_free",
    graph_arms: tuple[str, ...] = ("native", "text_adapter"),
) -> dict:
    document = _read(quality_path)
    if not document.get("all_arms_rankable"):
        raise ValueError("quality document is not fully rankable")

    arms = {arm["arm"]: arm for arm in document["arms"]}
    required = {candidate_arm, *graph_arms}
    missing = sorted(required - arms.keys())
    if missing:
        raise ValueError("missing arms: " + ", ".join(missing))

    strongest_graph_arm = max(
        graph_arms, key=lambda name: arms[name]["strict_success_macro"]
    )
    grouped: dict[str, dict[str, list[dict]]] = {}
    for arm_name, arm in arms.items():
        families: dict[str, list[dict]] = defaultdict(list)
        for session in arm["sessions"]:
            families[session["family"]].append(session)
        grouped[arm_name] = families

    candidate_sessions = arms[candidate_arm]["sessions"]
    buckets = Counter(_failure_bucket(session) for session in candidate_sessions)
    deficient_dimensions = Counter()
    for session in candidate_sessions:
        if session["quality"]["qa_success"]:
            continue
        for dimension, score in session["quality"].items():
            if dimension in {"qa_success", "first_answer_success", "answer_accuracy"}:
                continue
            if score is not None and score < 1:
                deficient_dimensions[dimension] += 1

    family_rows = []
    for family, sessions in sorted(grouped[candidate_arm].items()):
        category = sessions[0]["category"]
        arm_metrics = {}
        for arm_name in arms:
            family_sessions = grouped[arm_name][family]
            arm_metrics[arm_name] = {
                metric: _average(family_sessions, metric) for metric in METRICS
            }
        candidate_success = arm_metrics[candidate_arm]["qa_success"]
        strongest_success = arm_metrics[strongest_graph_arm]["qa_success"]
        failures = [
            {
                "question_id": session["question_id"],
                "bucket": _failure_bucket(session),
                "answer_accuracy": session["quality"].get("answer_accuracy"),
                "citation_accuracy": session["quality"].get("citation_accuracy"),
                "required_evidence_recall": session["quality"].get(
                    "required_evidence_recall"
                ),
            }
            for session in sessions
            if not session["quality"]["qa_success"]
        ]
        family_rows.append(
            {
                "family": family,
                "category": category,
                "candidate_minus_strongest_graph": candidate_success
                - strongest_success,
                "metrics_by_arm": arm_metrics,
                "candidate_failures": failures,
            }
        )

    family_rows.sort(
        key=lambda row: (row["candidate_minus_strongest_graph"], row["family"])
    )
    return {
        "schema": "dev-quality-error-analysis-v1",
        "quality_sha256": _sha256(quality_path),
        "candidate_arm": candidate_arm,
        "strongest_graph_arm": strongest_graph_arm,
        "candidate_failure_buckets": dict(sorted(buckets.items())),
        "candidate_deficient_dimensions": dict(
            sorted(deficient_dimensions.items(), key=lambda item: (-item[1], item[0]))
        ),
        "families": family_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-arm", default="principia_index_free")
    parser.add_argument(
        "--graph-arm", action="append", dest="graph_arms", default=[]
    )
    args = parser.parse_args()
    graph_arms = tuple(args.graph_arms) or ("native", "text_adapter")
    output = analyse(args.quality, args.candidate_arm, graph_arms)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "families": len(output["families"])}))


if __name__ == "__main__":
    main()
