"""评分侧新事实族候选盘点；不生成检索规则或图边，不读取新测试答案。"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sections(corpus):
    rows = []
    for file in sorted((corpus / "manual/markdown").glob("*.md")):
        lines = file.read_text().splitlines()
        headings = [(i, len(m[1]), m[2]) for i, line in enumerate(lines, 1)
                    if (m := re.match(r"^(#{1,6})\s+(.+)$", line))]
        for pos, (start, level, title) in enumerate(headings):
            # Keep leaf sections; parent contents duplicate their children's facts.
            if pos + 1 < len(headings) and headings[pos + 1][1] > level:
                continue
            end = next((i - 1 for i, depth, _ in headings[pos + 1:] if depth <= level), len(lines))
            rows.append({"path": file.relative_to(corpus).as_posix(), "start": start, "end": end,
                         "title": title, "sha256": sha(file), "text": "\n".join(lines[start - 1:end])})
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--graph", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--historical-dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("inventory is versioned")
    graph = json.loads(args.graph.read_text())
    history, historical_inputs = [], {}
    for split in ("dev", "holdout"):
        file = args.historical_dataset / (split + ".annotations.json")
        historical_inputs[file.name] = sha(file)
        history.extend(json.loads(file.read_text()))
    historical_ranges = defaultdict(list)
    for a in history:
        for atom in a["evidence"]:
            historical_ranges[atom["path"]].append((atom["start"], atom["end"], a["id"]))
    definitions = sections(args.corpus)
    for definition in definitions:
        definition["historical_definition_overlap"] = sorted({family for start, end, family in historical_ranges[definition["path"]]
                                                             if start <= definition["end"] and end >= definition["start"]})
    groups = {}
    for definition in definitions:
        matches = []
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z_0-9+]*", definition["title"]))
        # Exact heading identifier only; this is a candidate join, never proof of a semantic relation.
        for node in graph["nodes"].values():
            if node["kind"] != "configuration" or not node["path"].startswith("tutorials/"):
                continue
            value = str(node.get("value", "")).strip().strip('"')
            if value not in tokens or len(value) < 3 or value.lower() in {"models", "model", "the", "and", "none"}:
                continue
            scope = node.get("scope", {})
            if not scope.get("case_directory"):
                continue
            evidence = node.get("evidence", [])
            if not evidence:
                continue
            exposed = sorted({family for e in evidence for start, end, family in historical_ranges[e["path"]]
                              if start <= e["end"] and end >= e["start"]})
            matches.append({"node_id": node["id"], "key": node.get("key"), "value": value,
                            "dictionary": node.get("dictionary"), "scope": scope,
                            "evidence": evidence, "historical_instance_overlap": exposed})
        if matches:
            identity = f"{definition['path']}:{definition['start']}"
            groups[identity] = {"definition": definition, "instances": matches,
                                "status": "exposed_definition" if definition["historical_definition_overlap"] else "needs_semantic_review",
                                "independence_policy": "same manual definition across cases is one cluster; synonyms and shared definitions need review before splitting"}
    out = {"schema": "independent-fact-inventory-v1", "graph_sha256": sha(args.graph),
           "historical_annotations_sha256": historical_inputs, "implementation_sha256": sha(Path(__file__)),
           "historical_families": len(history), "manual_leaf_sections": len(definitions),
           "cross_candidate_clusters": len(groups),
           "unexposed_definition_clusters": sum(g["status"] == "needs_semantic_review" for g in groups.values()),
           "cross_candidates": groups,
           "single_source_manual_candidates": [d for d in definitions if not d["historical_definition_overlap"]],
           "limits": "exact name matching is only inventory; excludes section overlaps conservatively, not a semantic novelty certificate; no dataset is frozen"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in {"cross_candidates", "single_source_manual_candidates"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
