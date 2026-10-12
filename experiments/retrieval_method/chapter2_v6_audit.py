"""验证新版第2章题集的冻结输入、证据和事实族隔离。"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


def load(path):
    return json.loads(path.read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--v5", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    a = p.parse_args()
    manifest = load(a.dataset / "manifest.json")
    if manifest["schema"] not in ("natural-navigation-qa-v6r1", "natural-navigation-qa-v7-20-80", "natural-navigation-qa-v7r1-20-80"):
        raise ValueError("unexpected schema")
    for name, expected in manifest["artifacts"].items():
        if digest((a.dataset / name).read_bytes()) != expected:
            raise ValueError("artifact changed: " + name)
    if manifest["parent_v5_manifest_sha256"] != digest((a.v5 / "manifest.json").read_bytes()):
        raise ValueError("v5 parent drift")
    corpus = load(a.dataset / "corpus-manifest.json")
    if corpus != load(a.v5 / "corpus-manifest.json"):
        raise ValueError("corpus manifest drift")
    questions = {s: load(a.dataset / f"{s}.questions.json") for s in ("dev", "holdout")}
    annotations = {s: load(a.dataset / f"{s}.annotations.json") for s in ("dev", "holdout")}
    all_questions = questions["dev"] + questions["holdout"]
    if len(all_questions) != 300 or len({q["id"] for q in all_questions}) != 300:
        raise ValueError("not 300 unique question IDs")
    if len({q["question"].strip() for q in all_questions}) != 300:
        raise ValueError("duplicate public text")
    categories = {}
    evidence_intervals = []
    for split in ("dev", "holdout"):
        if len(annotations[split]) != manifest["counts"][split + "_families"] or len(questions[split]) != manifest["counts"][split + "_questions"]:
            raise ValueError("incorrect split size")
        family_ids = [x["family"] for x in annotations[split]]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("duplicate family annotation")
        qcount = Counter(q["family_id"] for q in questions[split])
        if set(qcount) != set(family_ids) or any(n != 6 for n in qcount.values()):
            raise ValueError("not six variants per family")
        for annotation in annotations[split]:
            family = annotation["family"]
            categories[family] = (split, annotation["category"])
            for e in annotation["evidence"]:
                path = e["path"]
                if path not in corpus:
                    raise ValueError("evidence outside corpus: " + path)
                raw = (a.corpus / path).read_bytes()
                lines = raw.decode().splitlines()
                if digest(raw) != e["sha256"] or digest(raw) != corpus[path]["sha256"]:
                    raise ValueError("source hash drift: " + path)
                quote = "\n".join(lines[e["start"] - 1:e["end"]])
                if quote != e["quote"] or digest(quote.encode()) != e["quote_sha256"]:
                    raise ValueError("quote drift: " + e["id"])
                evidence_intervals.append((family, split, path, e["start"], e["end"]))
        for question in questions[split]:
            if question["split"] != split or not 18 <= len(question["question"]) <= 240:
                raise ValueError("question split/length: " + question["id"])
            if re.search(r"^(?:这两个|上述|它们|这种|这个)\b", question["question"]):
                raise ValueError("unanchored public question: " + question["id"])
    if set(categories) != set(manifest["split_by_family"]):
        raise ValueError("manifest family mismatch")
    if any(categories[f][0] != s for f, s in manifest["split_by_family"].items()):
        raise ValueError("manifest split mismatch")
    category_count = Counter(categories.values())
    expected = ({("dev", "tutorial"): 12, ("dev", "manual"): 12, ("dev", "cross"): 11,
                 ("holdout", "tutorial"): 5, ("holdout", "manual"): 5, ("holdout", "cross"): 5}
                if manifest["schema"] == "natural-navigation-qa-v6r1" else
                {("dev", "tutorial"): 4, ("dev", "manual"): 3, ("dev", "cross"): 3,
                 ("holdout", "tutorial"): 13, ("holdout", "manual"): 14, ("holdout", "cross"): 13})
    if dict(category_count) != expected:
        raise ValueError(f"category allocation {category_count}")
    old_holdout = {x["family"] for x in load(a.v5 / "holdout.annotations.json")}
    if not old_holdout <= {x["family"] for x in annotations["holdout"]}:
        raise ValueError("old holdout family leaked")
    # v5 contains a few pre-existing broad evidence spans across its splits.
    # The new version must introduce no additional cross-split overlap.
    for i, (family, split, path, start, end) in enumerate(evidence_intervals):
        for other, other_split, other_path, other_start, other_end in evidence_intervals[:i]:
            if family in old_holdout | {x["family"] for x in load(a.v5 / "dev.annotations.json")} and other in old_holdout | {x["family"] for x in load(a.v5 / "dev.annotations.json")}:
                continue
            if split != other_split and path == other_path and start <= other_end and other_start <= end:
                raise ValueError(f"new cross-split evidence overlap: {family}/{other} {path}")
    old_public = load(a.v5 / "dev.questions.json") + load(a.v5 / "holdout.questions.json")
    old_by_id = {q["id"]: q for q in old_public}
    for q in all_questions:
        if q["id"] in old_by_id and {k: v for k, v in q.items() if k != "split"} != {k: v for k, v in old_by_id[q["id"]].items() if k != "split"}:
            raise ValueError("old variant changed: " + q["id"])
    print(json.dumps({"status": "pass", "families": 50, "questions": 300,
                      "dev": len(questions["dev"]), "holdout": len(questions["holdout"]), "categories": {str(k): v for k, v in category_count.items()},
                      "source_files": len(corpus), "old_holdout_retained": len(old_holdout)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
