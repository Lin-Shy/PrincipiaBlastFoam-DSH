"""开发轨迹的确定性失败归因；gold仅在此评分侧读取。"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coordinates(ranges):
    result = defaultdict(set)
    for r in ranges:
        result[r["path"]].update(range(r["start"], r["end"] + 1))
    return result


def analyse(run):
    arm = run / "principia_index_free"
    graph = read(run / "principia-graph.json")
    graph_ranges = coordinates(a for n in graph["nodes"].values() for a in n.get("evidence", []))
    annotations = {a["id"]: a for a in read(arm / "evaluation_only/annotations.json")}
    rows = []
    for file in sorted(arm.glob("sessions/*/result.json")):
        result = read(file)
        annotation = annotations[result["item_id"]]
        if annotation["split"] != "dev":
            raise ValueError("development audit only")
        seen = {p: set(map(int, lines)) for p, lines in result["seen_lines"].items()}
        candidates, selected = [], []
        pending = {}
        tool_budget_violations = []
        for i, event in enumerate(result["events"]):
            action, payload = event["action"], event.get("result", {})
            if event.get("returned_characters", 0) > 6000:
                tool_budget_violations.append(i)
            if action.get("action") == "locate":
                pending = {c["id"]: c for c in payload.get("candidates", [])}
                candidates.extend(r for c in pending.values() for r in c.get("sources", []))
            elif action.get("action") == "read_sources":
                selected.extend(r for cid in action.get("candidate_ids", []) for r in pending.get(cid, {}).get("sources", []))
        candidate_coords, selected_coords = coordinates(candidates), coordinates(selected)
        atoms = []
        for atom in annotation["evidence"]:
            path = atom["path"]
            needed = set(range(atom["start"], atom["end"] + 1))
            delivered = needed <= seen.get(path, set())
            if delivered:
                bucket = "delivered"
            elif path not in graph_ranges:
                bucket = "no_graph_anchor_in_required_file"
            elif not candidate_coords.get(path):
                bucket = "required_file_absent_from_navigation_candidates"
            elif needed <= selected_coords.get(path, set()):
                bucket = "selected_range_not_fully_delivered"
            elif needed <= candidate_coords.get(path, set()):
                bucket = "complete_candidate_not_selected"
            else:
                bucket = "candidate_ranges_incomplete"
            atoms.append({"id": atom["id"], "path": path, "start": atom["start"], "end": atom["end"],
                          "delivered": delivered, "seen_fraction": len(needed & seen.get(path, set())) / len(needed),
                          "direct_graph_anchor_complete": needed <= graph_ranges.get(path, set()), "bucket": bucket})
        refs = result.get("parsed_answer", {}).get("references", [])
        checks = []
        for ref in refs:
            start, end, path = ref.get("start"), ref.get("end"), ref.get("path")
            valid = type(start) is int and type(end) is int and 1 <= start <= end
            checks.append(valid and set(range(start, end + 1)) <= seen.get(path, set()))
        rows.append({"id": result["id"], "family": annotation["id"], "category": annotation["category"],
                     "result_sha256": sha(file), "status": result["status"], "atoms": atoms,
                     "complete_evidence_set": all(a["delivered"] for a in atoms),
                     "returned_characters": result["returned_characters"],
                     "tool_budget_violations": tool_budget_violations,
                     "total_budget_violation": result["returned_characters"] > 24000,
                     "citation_coordinate_checks": checks,
                     "answer_semantic_score": None})
    return {"schema": "development-delivery-audit-v1", "protocol_sha256": sha(run / "protocol.json"),
            "graph_sha256": sha(run / "principia-graph.json"), "implementation_sha256": sha(Path(__file__)),
            "annotation_sha256": sha(arm / "evaluation_only/annotations.json"), "rows": rows,
            "failure_atoms": dict(Counter(a["bucket"] for r in rows for a in r["atoms"])),
            "complete_sets": sum(r["complete_evidence_set"] for r in rows), "sessions": len(rows),
            "limits": "导航候选缺失不区分种子、遍历与排序原因；行覆盖与引用坐标不证明回答语义正确。"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("use a new audit version")
    out = analyse(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False))
