"""Bound strict success and paired differences under unresolved source reviews."""
import argparse
import json
from pathlib import Path


ARMS = ("control", "native", "text_adapter", "principia_index_free", "vector_e5_dense")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quality", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    quality = json.loads(a.quality.read_text())
    if quality["split"] not in ("dev", "holdout"):
        raise ValueError("unknown quality split")
    methods = quality["methods"]
    bounds = {}
    for arm in ARMS:
        row = methods[arm]
        planned, success, missing = row["planned_sessions"], row["strict_successes"], row["unresolved_reviews"]
        if row["compiled_reviews"] != planned or success + missing > planned:
            raise ValueError("review denominator mismatch")
        bounds[arm] = {"planned": planned, "observed_successes": success,
                       "unresolved_reviews": missing, "lower_success_rate": success/planned,
                       "upper_success_rate_if_all_unresolved_succeed": (success+missing)/planned}
    self_row = bounds["principia_index_free"]
    paired_bounds = {}
    for arm in ARMS:
        if arm == "principia_index_free":
            continue
        other = bounds[arm]
        if self_row["planned"] != other["planned"]:
            raise ValueError("methods have unequal planned denominators")
        n = self_row["planned"]
        paired_bounds["principia_minus_" + arm] = {
            "observed_conservative_difference": (self_row["observed_successes"]-other["observed_successes"])/n,
            "worst_case_lower_difference_if_only_comparator_missing_succeed":
                (self_row["observed_successes"]-other["observed_successes"]-other["unresolved_reviews"])/n,
            "worst_case_upper_difference_if_only_self_missing_succeed":
                (self_row["observed_successes"]+self_row["unresolved_reviews"]-other["observed_successes"])/n}
    result = {"schema": "chapter2-v7-unresolved-review-deterministic-bounds-v1", "split": quality["split"],
              "quality_report_sha256": __import__("hashlib").sha256(a.quality.read_bytes()).hexdigest(),
              "interpretation": "Logical bounds only, not confidence intervals. Each structurally invalid or uncertain review may be either strict success or failure; no score is imputed in the primary report.",
              "methods": bounds, "differences": paired_bounds}
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({arm: value["unresolved_reviews"] for arm, value in bounds.items()}))


if __name__ == "__main__":
    main()
