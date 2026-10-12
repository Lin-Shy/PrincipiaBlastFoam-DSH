"""按事实族汇总新版五臂盲审结果，计算配对 bootstrap 置信区间。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
import statistics

from chapter2_segmented_timing import percentile

ARMS = ("control", "native", "text_adapter", "principia_index_free", "vector_e5_dense")
SEED = 20260928
RESAMPLES = 10000


def load(path):
    return json.loads(path.read_text())


def paired_ci(families, left, right):
    differences = [left[f] - right[f] for f in families]
    rng = random.Random(SEED)
    boot = [statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(RESAMPLES)]
    return {"difference": statistics.mean(differences), "lower_95": percentile(boot, .025),
            "upper_95": percentile(boot, .975), "families": len(families)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--reviews", type=Path, required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--split", choices=("dev", "holdout"), required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("quality output exists")
    run_protocol = load(a.run / "protocol.json")
    dataset = load(a.dataset / "manifest.json")
    if run_protocol["dataset_manifest_sha256"] != __import__("hashlib").sha256((a.dataset / "manifest.json").read_bytes()).hexdigest():
        raise ValueError("run/dataset mismatch")
    if run_protocol["split"] != a.split:
        raise ValueError("run split mismatch")
    questions = load(a.dataset / f"{a.split}.questions.json")
    families = sorted({q["family_id"] for q in questions})
    expected = {f: [q["id"] for q in questions if q["family_id"] == f] for f in families}
    results = {}
    for arm in ARMS:
        method = run_protocol["groups"][arm][0]
        for q in questions:
            for rep in range(1, run_protocol["replicates"] + 1):
                session = f"{q['id']}--{method}--r{rep}"
                path = a.run / arm / "sessions" / session / "result.json"
                results[(arm, session)] = load(path) if path.is_file() else None
    review_map_path = a.reviews / "evaluation_only" / "blind-map.json"
    if not review_map_path.exists():
        raise ValueError("blind review map unavailable")
    review_map = load(review_map_path)
    quality = {}
    compiled_counts = defaultdict(int)
    unresolved_counts = defaultdict(int)
    for blind_id, binding in review_map.items():
        path = a.reviews / "sessions" / blind_id / "compiled.json"
        if not path.is_file():
            continue
        compiled = load(path)
        if compiled.get("binding") != binding:
            raise ValueError("review binding drift")
        compiled_counts[binding["arm"]] += 1
        if compiled.get("status") == "reviewed" and compiled.get("quality") is not None:
            quality[(binding["arm"], binding["session"])] = compiled["quality"]
        else:
            unresolved_counts[binding["arm"]] += 1
    by_arm = {}
    family_rates = {}
    for arm in ARMS:
        family_rates[arm] = {}
        reviewed = complete = successes = 0
        citations = []
        for family in families:
            sessions = [f"{qid}--{run_protocol['groups'][arm][0]}--r{rep}"
                        for qid in expected[family] for rep in range(1, run_protocol["replicates"] + 1)]
            values = []
            for session in sessions:
                result = results[(arm, session)]
                complete += bool(result and result.get("status") == "complete")
                score = quality.get((arm, session))
                if score is not None:
                    reviewed += 1
                    success = int(score["qa_success"] is True)
                    successes += success
                    values.append(success)
                    if score.get("citation_accuracy") is not None:
                        citations.append(float(score["citation_accuracy"]))
                else:
                    values.append(0)  # conservative planned denominator; missing separately reported
            family_rates[arm][family] = statistics.mean(values)
        planned = len(questions) * run_protocol["replicates"]
        by_arm[arm] = {"planned_sessions": planned, "complete_answers": complete,
                       "compiled_reviews": compiled_counts[arm], "reviewed_sessions": reviewed,
                       "unresolved_reviews": unresolved_counts[arm], "unreviewed_or_missing": planned - reviewed,
                       "strict_successes": successes,
                       "strict_success_planned_denominator": statistics.mean(family_rates[arm].values()),
                       "citation_accuracy_reviewed_mean": statistics.mean(citations) if citations else None}
    comparisons = {}
    if any(row["compiled_reviews"] != row["planned_sessions"] for row in by_arm.values()):
        raise ValueError("review grid incomplete; do not publish partial method scores")
    for comparator in ("control", "native", "text_adapter", "vector_e5_dense"):
        comparisons["principia_minus_" + comparator] = paired_ci(families, family_rates["principia_index_free"], family_rates[comparator])
    report = {"schema": "chapter2-v7-family-paired-quality-v1", "split": a.split,
              "dataset_manifest_sha256": run_protocol["dataset_manifest_sha256"],
              "run_protocol_sha256": __import__("hashlib").sha256((a.run / "protocol.json").read_bytes()).hexdigest(),
              "review_protocol_sha256": __import__("hashlib").sha256((a.reviews / "protocol.json").read_bytes()).hexdigest(),
              "families": len(families), "questions": len(questions), "replicates": run_protocol["replicates"],
              "denominator": "family macro mean of six variants x replicates; missing/unresolved scored zero conservatively and counted separately",
              "bootstrap": {"seed": SEED, "resamples": RESAMPLES, "unit": "paired family"},
              "methods": by_arm, "paired_differences": comparisons}
    if a.split == "holdout":
        exposure = load(a.dataset / "exposure-audit.json")
        old_dev = set(exposure["old_v5_development_families_moved_to_holdout"])
        pilot = set(exposure["new_holdout_families_queried_in_pilot"])
        strata = {"old_v5_dev": sorted(old_dev), "pilot_queried_only": sorted(pilot - old_dev),
                  "neither_recorded_exposure": sorted(set(families) - old_dev - pilot)}
        report["internal_exposure_strata"] = {name: {"families": len(ids),
            "methods": {arm: statistics.mean(family_rates[arm][f] for f in ids) if ids else None for arm in ARMS}}
            for name, ids in strata.items()}
    a.output.mkdir(parents=True)
    (a.output / "quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({arm: x["strict_success_planned_denominator"] for arm, x in by_arm.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
