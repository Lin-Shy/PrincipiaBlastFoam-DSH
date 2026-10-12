"""仅在数据审计侧核对候选必要原文是否曾由历史会话实际送达。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--drafts", type=Path, required=True)
    p.add_argument("--history", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("choose a new audit version")
    families = json.loads(args.drafts.read_text())["families"]
    originals = {}
    rows = {}
    for family in families:
        atoms = []
        for atom in family["evidence"]:
            path = atom["path"]
            file = args.corpus / path
            if sha(file) != atom["sha256"]:
                raise ValueError("authoritative source drift")
            originals.setdefault(path, file.read_text().splitlines())
            atoms.append({"id": atom["id"], "path": path, "start": atom["start"], "end": atom["end"],
                          "complete_session_count": 0, "partial_session_count": 0, "seen_union": set()})
        rows[family["id"]] = {"id": family["id"], "category": family["category"], "atoms": atoms,
                               "complete_set_in_one_session": 0, "sample_complete_sessions": []}
    manifest = {}
    unusable, mismatched, statuses = [], [], Counter()
    results = sorted(args.history.glob("*/**/sessions/*/result.json"))
    for index, file in enumerate(results, 1):
        relative = str(file.relative_to(args.history))
        manifest[relative] = sha(file)
        result = json.loads(file.read_text())
        seen = result.get("seen_lines")
        if not isinstance(seen, dict):
            unusable.append(relative)
            continue
        statuses[result.get("status")] += 1
        verified = {}
        for path, lines in seen.items():
            if path not in originals or not isinstance(lines, dict):
                continue
            raw = originals[path]
            verified[path] = set()
            for key, value in lines.items():
                try:
                    n = int(key)
                except (ValueError, TypeError):
                    continue
                if 1 <= n <= len(raw) and value == raw[n-1]:
                    verified[path].add(n)
                else:
                    mismatched.append({"session": relative, "path": path, "line": key})
        for family in rows.values():
            full = True
            for atom in family["atoms"]:
                needed = set(range(atom["start"], atom["end"] + 1))
                overlap = needed & verified.get(atom["path"], set())
                atom["seen_union"].update(overlap)
                if overlap == needed:
                    atom["complete_session_count"] += 1
                else:
                    full = False
                    if overlap:
                        atom["partial_session_count"] += 1
            if full:
                family["complete_set_in_one_session"] += 1
                if len(family["sample_complete_sessions"]) < 3:
                    family["sample_complete_sessions"].append(relative)
        if index % 1000 == 0:
            print("SCANNED", index, "/", len(results), flush=True)
    for family in rows.values():
        family["complete_set_in_historical_union"] = all(len(a["seen_union"]) == a["end"] - a["start"] + 1 for a in family["atoms"])
        for atom in family["atoms"]:
            atom["union_seen_fraction"] = len(atom["seen_union"]) / (atom["end"] - atom["start"] + 1)
            del atom["seen_union"]
    out = {"schema": "historical-delivered-evidence-exposure-v1", "drafts_sha256": sha(args.drafts),
           "implementation_sha256": sha(Path(__file__)), "historical_result_sha256": manifest,
           "history_sessions": len(results), "usable_sessions": len(results)-len(unusable), "statuses": dict(statuses),
           "unusable_sessions": unusable, "source_line_mismatches": mismatched, "rows": list(rows.values()),
           "complete_set_exposed_families": sum(r["complete_set_in_one_session"] > 0 for r in rows.values()),
           "limits": "覆盖的是当前保留的历史结果及其实际seen_lines；不覆盖删除材料和未记录送达。曾送达原文不等于曾问过同一事实组合，不能据新问法声称未见语料。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"history_sessions": len(results), "unusable": len(unusable), "mismatches": len(mismatched),
                      "complete_set_exposed_families": out["complete_set_exposed_families"]}))


if __name__ == "__main__":
    main()
