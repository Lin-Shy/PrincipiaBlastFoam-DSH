"""将 50 族题集按 20/80 重分组，并归档先导调用暴露情况。"""
from collections import Counter
import argparse
import json
from pathlib import Path
import time

from build_natural_navigation_v2 import sha, wire, write
from build_natural_navigation_v6 import read

DEV_QUOTA = {"tutorial": 4, "manual": 3, "cross": 3}
SEED = "20260928-v7-20-80"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parent", type=Path, required=True)
    p.add_argument("--v5", type=Path, required=True)
    p.add_argument("--discarded-pilot", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("v7 output exists")
    a.output.mkdir(parents=True)
    parent = {s: {"questions": read(a.parent / f"{s}.questions.json"),
                  "annotations": read(a.parent / f"{s}.annotations.json")} for s in ("dev", "holdout")}
    old_dev = read(a.v5 / "dev.annotations.json")
    old_holdout = {x["family"] for x in read(a.v5 / "holdout.annotations.json")}
    selected = set()
    for category, quota in DEV_QUOTA.items():
        candidates = [x["family"] for x in old_dev if x["category"] == category]
        candidates.sort(key=lambda family: sha(f"{SEED}:{category}:{family}"))
        selected.update(candidates[:quota])
    if len(selected) != 10 or selected & old_holdout:
        raise ValueError("invalid dev selection")
    all_annotations = [x for s in parent.values() for x in s["annotations"]]
    all_questions = [x for s in parent.values() for x in s["questions"]]
    original_dev = {x["family"] for x in old_dev}
    split_by_family = {a["family"]: "dev" if a["family"] in selected else "holdout" for a in all_annotations}
    new = {s: {"questions": [], "annotations": []} for s in ("dev", "holdout")}
    for row in all_annotations:
        updated = {**row, "split": split_by_family[row["family"]]}
        new[updated["split"]]["annotations"].append(updated)
    for row in all_questions:
        updated = {**row, "split": split_by_family[row["family_id"]]}
        new[updated["split"]]["questions"].append(updated)
    for split, family_count, question_count in (("dev", 10, 60), ("holdout", 40, 240)):
        if len(new[split]["annotations"]) != family_count or len(new[split]["questions"]) != question_count:
            raise ValueError("incorrect 20/80 split")
        write(a.output / f"{split}.annotations.json", sorted(new[split]["annotations"], key=lambda x: x["legacy_id"]))
        write(a.output / f"{split}.questions.json", sorted(new[split]["questions"], key=lambda x: x["id"]))
    for name in ("corpus-manifest.json", "scoring-rules.json", "review-summary.json", "repair-summary.json"):
        write(a.output / name, read(a.parent / name))
    queried = {}
    pilot_root = a.discarded_pilot / "control" / "sessions"
    for path in sorted(pilot_root.glob("*/result.json")):
        obj = read(path)
        queried[obj["id"]] = {"family_id": obj["item_id"], "result_sha256": sha(path.read_bytes()),
                              "status": obj["status"]}
    exposed_families = {v["family_id"] for v in queried.values()}
    holdout_families = {x["family"] for x in new["holdout"]["annotations"]}
    exposure = {"discarded_pilot": str(a.discarded_pilot), "pilot_protocol_sha256": sha((a.discarded_pilot / "protocol.json").read_bytes()),
                "pilot_queried_questions": len(queried), "pilot_queried_families": len(exposed_families),
                "new_holdout_families_queried_in_pilot": sorted(holdout_families & exposed_families),
                "old_v5_development_families_moved_to_holdout": sorted(original_dev & holdout_families),
                "old_v5_holdout_families_retained": sorted(old_holdout),
                "interpretation": "Discarded pilot answers are not scored or used for selection. The moved old-dev families and pilot-queried families are not pristine holdout facts; disclose this limitation.",
                "queried_question_records": queried}
    write(a.output / "exposure-audit.json", exposure)
    artifact_hashes = {p.relative_to(a.output).as_posix(): sha(p.read_bytes()) for p in sorted(a.output.rglob("*"))
                       if p.is_file() and p.name != "manifest.json"}
    manifest = dict(read(a.parent / "manifest.json"))
    manifest.update({"schema": "natural-navigation-qa-v7-20-80", "created_unix_ns": time.time_ns(),
                     "parent_v6r1_manifest_sha256": sha((a.parent / "manifest.json").read_bytes()),
                     "split_seed": SEED, "split_by_family": split_by_family,
                     "counts": {"dev_families": 10, "dev_questions": 60, "holdout_families": 40, "holdout_questions": 240},
                     "category_counts": {split: dict(Counter(x["category"] for x in new[split]["annotations"])) for split in new},
                     "artifacts": artifact_hashes})
    write(a.output / "manifest.json", manifest)
    print(wire({"counts": manifest["counts"], "category_counts": manifest["category_counts"],
                "old_dev_moved": len(exposure["old_v5_development_families_moved_to_holdout"]),
                "holdout_families_queried_in_discarded_pilot": len(exposure["new_holdout_families_queried_in_pilot"])}))


if __name__ == "__main__":
    main()
