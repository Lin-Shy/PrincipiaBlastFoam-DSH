"""将 v6 人工审阅发现的四族问题修正为可审计的新版本，不覆盖原始产物。"""
import argparse
import json
from pathlib import Path
import time

from build_natural_navigation_v2 import sha, wire, write
from build_natural_navigation_v6 import credential, read, request, STYLES


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parent", type=Path, required=True)
    p.add_argument("--repairs", type=Path, required=True)
    p.add_argument("--settings", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if (a.output / "manifest.json").exists():
        raise FileExistsError("repaired dataset already frozen")
    a.output.mkdir(parents=True, exist_ok=True)
    key = credential(a.settings)
    repairs = read(a.repairs)
    if set(repairs) != {"fsi-flap-scenario-and-stability", "reactingparticles-drag-model-instance",
                        "internal-detonation-miller-afterburn", "reactingparticles-heattransfer-model"}:
        raise ValueError("unexpected repair families")
    public = {split: read(a.parent / f"{split}.questions.json") for split in ("dev", "holdout")}
    private = {split: read(a.parent / f"{split}.annotations.json") for split in ("dev", "holdout")}
    audit = []
    for family, replacement in repairs.items():
        split = next(split for split in private if any(row["family"] == family for row in private[split]))
        annotation = next(row for row in private[split] if row["family"] == family)
        evidence = [{k: e[k] for k in ("path", "start", "end", "quote")} for e in annotation["evidence"]]
        questions = replacement["questions"]
        if len(questions) != 6 or any(not 18 <= len(q) <= 240 for q in questions):
            raise ValueError("invalid replacement count/length: " + family)
        gold = replacement.get("gold", annotation["gold"])
        reviews = []
        for reviewer in (1, 2):
            prompt = {"task": "审核修订后的六道公开检索问题", "reviewer": reviewer,
                      "family": family, "category": annotation["category"], "gold": gold,
                      "evidence": evidence, "questions": questions, "styles": list(STYLES),
                      "requirements": ["独立审核每一道问题，必须正好给六个逐题结果。",
                                       "询问答案值是正常问题；题干直接断言答案值才是泄露。",
                                       "每题都要覆盖同一 gold，跨来源族必须同时需要手册和教程证据。",
                                       "题目无需隐藏真实的模型或案例自然名称，但不得依赖隐藏上下文。"],
                      "output_format_example": {"items": [{"index": i, "pass": True, "reason": ""} for i in range(6)]}}
            record = a.output / "repair-reviews" / family / f"review-{reviewer}-{sha(wire(prompt))[:12]}.json"
            value = request(prompt, key, record)
            items = value.get("items") if isinstance(value, dict) else None
            if not isinstance(items, list) or len(items) != 6:
                raise ValueError("malformed reviewer output: " + family)
            by_index = {int(item["index"]): item for item in items}
            if set(by_index) != set(range(6)) or any(item.get("pass") is not True for item in by_index.values()):
                raise ValueError("repair review rejected " + family + ": " + str(items))
            reviews.append(items)
        annotation["gold"] = gold
        rows = [q for q in public[split] if q["family_id"] == family]
        rows.sort(key=lambda q: int(q["id"].split("-n")[-1]))
        if len(rows) != 6:
            raise ValueError("not six public questions: " + family)
        for row, question in zip(rows, questions):
            row["question"] = question
        audit.append({"family": family, "split": split, "reason": "manual semantic audit found leaked answer, missing cross-source request, or unsupported scenario", "reviews": reviews})
    all_questions = [q["question"] for split in public for q in public[split]]
    if len(all_questions) != len(set(all_questions)):
        raise ValueError("duplicate public question")
    for split in ("dev", "holdout"):
        write(a.output / f"{split}.questions.json", public[split])
        write(a.output / f"{split}.annotations.json", private[split])
    for name in ("corpus-manifest.json", "scoring-rules.json", "review-summary.json"):
        write(a.output / name, read(a.parent / name))
    write(a.output / "repair-summary.json", audit)
    artifacts = {path.relative_to(a.output).as_posix(): sha(path.read_bytes()) for path in sorted(a.output.rglob("*"))
                 if path.is_file() and path.name != "manifest.json"}
    manifest = dict(read(a.parent / "manifest.json"))
    manifest.update({"schema": "natural-navigation-qa-v6r1", "created_unix_ns": time.time_ns(),
                     "parent_v6_manifest_sha256": sha((a.parent / "manifest.json").read_bytes()),
                     "repairs_sha256": sha(a.repairs.read_bytes()), "artifacts": artifacts})
    write(a.output / "manifest.json", manifest)
    print(json.dumps({"schema": manifest["schema"], "counts": manifest["counts"], "repairs": len(audit)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
