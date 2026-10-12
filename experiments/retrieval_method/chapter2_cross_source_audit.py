"""离线审计活动图、权威原文锚点与历史结果；不读取评测gold。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(graph_path, corpus, historical):
    graph = json.loads(graph_path.read_text())
    nodes = graph["nodes"]
    manifest = {}
    errors = []
    anchors_checked = 0
    trimmed_quotes = 0
    quote_warnings = []

    def check(anchor, owner):
        nonlocal anchors_checked, trimmed_quotes
        anchors_checked += 1
        path = anchor.get("path", "")
        source = (corpus / path).resolve()
        if not source.is_relative_to(corpus.resolve()) or not source.is_file():
            errors.append({"owner": owner, "path": path, "error": "missing_source"})
            return
        if path not in manifest:
            raw = source.read_bytes()
            manifest[path] = (hashlib.sha256(raw).hexdigest(), raw.decode().splitlines())
        sha, lines = manifest[path]
        start, end = anchor.get("start", 0), anchor.get("end", 0)
        if not 1 <= start <= end <= len(lines):
            errors.append({"owner": owner, "path": path, "error": "invalid_range"})
            return
        if anchor.get("source_sha256") and anchor["source_sha256"] != sha:
            errors.append({"owner": owner, "path": path, "error": "source_hash"})
        quote = "\n".join(lines[start - 1:end])
        if "quote" in anchor and anchor["quote"] != quote:
            if anchor["quote"] == quote.strip():
                trimmed_quotes += 1
            else:
                quote_warnings.append({"owner": owner, "path": path,
                                       "kind": "literal_excerpt" if anchor["quote"] in quote else "requires_review"})
        if anchor.get("quote_sha256") and anchor["quote_sha256"] != hashlib.sha256(quote.encode()).hexdigest():
            errors.append({"owner": owner, "path": path, "error": "quote_hash"})

    for node in nodes.values():
        for anchor in node.get("evidence", []):
            check(anchor, node["id"])
    cross = []
    for edge in graph["edges"]:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            errors.append({"owner": edge["id"], "error": "missing_endpoint"})
        for key in ("evidence", "instance_evidence", "definition_evidence"):
            for anchor in edge.get(key, []):
                check(anchor, edge["id"])
        if edge.get("instance_evidence") and edge.get("definition_evidence"):
            sources = {a["path"].split("/", 1)[0] for key in ("instance_evidence", "definition_evidence") for a in edge[key]}
            cross.append({"id": edge["id"], "relation": edge["relation"],
                          "scope": edge.get("scope"), "conditions": edge.get("conditions"),
                          "status": edge.get("status"), "tutorial_manual": sources == {"tutorials", "manual"},
                          "instance_evidence": edge["instance_evidence"], "definition_evidence": edge["definition_evidence"]})
    history = {}
    for name in ("dev_siliconflow_qwen3_8b_paced_v1", "holdout_v7r1_20_80"):
        root = historical / name
        results = list(root.glob("*/sessions/*/result.json"))
        history[name] = {"results": len(results), "states": dict(Counter(json.loads(p.read_text()).get("status") for p in results)),
                         "replay_invocations": sum(json.loads(p.read_text()).get("replay") is True for p in root.glob("*/sessions/*/invocations/*.json"))}
    return {"schema": "chapter2-cross-source-audit-v1", "graph_path": str(graph_path), "graph_sha256": digest(graph_path),
            "nodes": len(nodes), "edges": len(graph["edges"]), "node_kinds": dict(Counter(n["kind"] for n in nodes.values())),
            "relations": dict(Counter(e["relation"] for e in graph["edges"])),
            "explicit_instance_definition_edges": len(cross), "tutorial_manual_edges": sum(e["tutorial_manual"] for e in cross),
            "cross_case_count": len({e["scope"].get("case_directory") for e in cross if e["scope"]}),
            "anchors_checked": anchors_checked, "unique_sources_checked": len(manifest), "anchor_errors": errors,
            "quotes_with_outer_whitespace_removed": trimmed_quotes,
            "quote_warnings": quote_warnings,
            "quote_warning_counts": dict(Counter(q["kind"] for q in quote_warnings)),
            "limits": "坐标、哈希和引文检查不证明语义连接正确；调用次数不等于唯一成功重放数。",
            "cross_edges": cross, "historical": history}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.graph, args.corpus, args.historical)
    if args.output.exists():
        raise FileExistsError("audit output is immutable; choose a new version")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"cross_edges", "anchor_errors", "quote_warnings"}}, ensure_ascii=False))
    print("anchor_errors", len(result["anchor_errors"]))
