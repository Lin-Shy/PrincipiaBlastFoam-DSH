"""评测侧原生图来源审计：只诊断开发集证据是否有主来源节点，不产生答案评分。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def audit(run, output):
    protocol = read(run/"protocol.json")
    for name, expected in protocol["files"].items():
        if sha((run/name).read_bytes()) != expected:
            raise ValueError("Frozen artifact changed: "+name)
    annotations = read(run/"control/evaluation_only/annotations.json")
    rows = []
    for variant in ("native", "text_adapter"):
        root = run/variant
        inverse = read(root/"path-map.json")
        graph = read(root/"graphify-out/graph.json")
        by_path = defaultdict(list)
        source_by_id = {}
        for node in graph["nodes"]:
            original = inverse.get(node.get("source_file"))
            source_by_id[node["id"]] = original
            if original:
                by_path[original].append(node)
        for annotation in annotations:
            evidence = []
            for ev in annotation["evidence"]:
                raw = (root/"skill/corpus"/ev["path"]).read_bytes()
                if sha(raw) != ev["sha256"] or "\n".join(raw.decode().splitlines()[ev["start"]-1:ev["end"]]) != ev["quote"]:
                    raise ValueError("Evidence changed")
                matches = by_path[ev["path"]]
                evidence.append({"id":ev["id"],"path":ev["path"],"range":[ev["start"],ev["end"]],
                    "has_primary_source_node":bool(matches),
                    "nodes":[{k:n.get(k) for k in ("id","label","source_file","source_location","verification","_origin")} for n in matches],
                    "note":"Primary-source file presence does not establish extraction of this span, concept, dictionary scope or fact."})
            paths = {e["path"] for e in annotation["evidence"]}
            direct = []
            for edge in graph.get("links",graph.get("edges",[])):
                a,b = (source_by_id.get(edge[k]) for k in ("source","target"))
                if a in paths and b in paths and a.split("/")[0] != b.split("/")[0]:
                    direct.append({**edge,"source_original_path":a,"target_original_path":b})
            rows.append({"variant":variant,"item_id":annotation["id"],"category":annotation["category"],
                "evidence":evidence,"all_evidence_files_have_primary_nodes":all(e["has_primary_source_node"] for e in evidence),
                "direct_cross_source_edges_between_required_files":direct,
                "edge_note":"Direct primary-source matches only; not a claim that indirect paths, mentions or semantic support do not exist."})
    summary = []
    for variant in ("native","text_adapter"):
        for category in ("tutorial","manual","cross"):
            selected = [r for r in rows if r["variant"]==variant and r["category"]==category]
            summary.append({"variant":variant,"category":category,"items":len(selected),
                "items_with_all_required_primary_files":sum(r["all_evidence_files_have_primary_nodes"] for r in selected),
                "evidence_units":sum(len(r["evidence"]) for r in selected),
                "units_with_primary_file":sum(e["has_primary_source_node"] for r in selected for e in r["evidence"]),
                "items_with_direct_cross_source_edges":sum(bool(r["direct_cross_source_edges_between_required_files"]) for r in selected)})
    record = {"protocol_sha256":sha((run/"protocol.json").read_bytes()),"driver_sha256":sha(Path(__file__).read_bytes()),
        "split":"dev","model_calls":0,"purpose":"evaluation_only_not_construction_input_not_quality_score", "summary":summary,"items":rows}
    if output.exists():
        raise FileExistsError("Preserve previous audit")
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"output":str(output),"summary":summary},ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    audit(args.run,args.output)
