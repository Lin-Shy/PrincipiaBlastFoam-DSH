"""以权威手册层级及配置声明构建通用角色对应；不读取题集或gold。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

from chapter2_production_guard import install


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()


def words(value):
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or ""))
    result = set()
    for token in re.findall(r"[a-z]+", value.casefold()):
        if token in {"a", "an", "and", "of", "for", "the", "type", "types", "model", "models", "scheme", "schemes"}:
            continue
        if token.endswith("ies") and len(token) > 5:
            token = token[:-3]+"y"
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        result.add(token)
    return result


def compatible(role, context, *, key):
    requested, available = words(role), words(context)
    if key == "application":
        return bool(available & {"solver", "utility", "utilities", "application", "program"})
    if not requested:
        return False
    matched = {r for r in requested if any(r == a or (min(len(r), len(a)) >= 5 and
                    (r.startswith(a) or a.startswith(r))) or
                    (r.startswith("integrat") and a.startswith("integrat")) for a in available)}
    return len(matched) == len(requested)


def manual_sections(path, lines):
    headings, fence = [], None
    for number, line in enumerate(lines, 1):
        marker = re.match(r"^\s*(```+|~~~+)", line)
        if marker:
            kind = marker[1][0]
            fence = None if fence == kind else kind if fence is None else fence
            continue
        if fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((number, len(match[1]), match[2]))
    ancestors, result = [], []
    for position, (start, level, title) in enumerate(headings):
        while ancestors and ancestors[-1][1] >= level:
            ancestors.pop()
        parents = [item[2] for item in ancestors]
        ancestors.append((start, level, title))
        if position+1 < len(headings) and headings[position+1][1] > level:
            continue
        end = next((n-1 for n, depth, _ in headings[position+1:] if depth <= level), len(lines))
        while end > start and not lines[end-1].strip():
            end -= 1
        clean = re.sub(r"^\d+(?:\.\d+)*\s+", "", title).strip()
        first = start+1
        while first <= end and not lines[first-1].strip():
            first += 1
        last = first
        while last < end and lines[last].strip():
            last += 1
        purpose = "\n".join(lines[first-1:last]) if first <= end else ""
        names = []
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_+.-]*(?:\([^\n]*\))?", clean):
            names = [re.match(r"[A-Za-z_][A-Za-z0-9_+.-]*", clean)[0]]
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_+.-]*(?:/[A-Za-z_][A-Za-z0-9_+.-]*)+", clean):
            # 共享章节只在首段明确列出每个可选名称时展开；不是推测同义词。
            candidates = clean.split("/")
            if "selectable" in purpose.casefold() and all(re.search(r"(?<![A-Za-z0-9_])"+re.escape(n)+r"(?![A-Za-z0-9_])", purpose) for n in candidates):
                names = candidates
        if not names:
            continue
        conditions = [{"path": path, "start": i, "end": i, "text": lines[i-1], "status": "literal_condition_not_evaluated"}
                      for i in range(start+1, end+1) if re.search(r"\b(only|valid|require[sd]?|must|when|assumes?|cannot)\b", lines[i-1], re.I)]
        for name in names:
            result.append({"path": path, "start": start, "end": end, "title": title, "model_identifier": name,
                       "ancestors": parents, "purpose": purpose, "role_context": " ".join(parents)+" "+purpose,
                       "conditions": conditions})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-graph", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new graph construction version required")
    started = time.monotonic()
    guard = install(offline=True)
    original_bytes = args.base_graph.read_bytes()
    graph = json.loads(original_bytes)
    nodes = graph["nodes"]
    sources = {}
    for file in sorted(args.corpus.rglob("*")):
        if file.is_file():
            raw = file.read_bytes()
            try:
                text = raw.decode()
            except UnicodeDecodeError:
                continue
            if "\x00" not in text:
                sources[file.relative_to(args.corpus).as_posix()] = {"sha256": digest(raw), "lines": text.splitlines()}
    definitions = []
    for path, source in sources.items():
        if path.startswith("manual/") and path.endswith(".md"):
            definitions.extend(manual_sections(path, source["lines"]))
    for definition in definitions:
        identity = "principia.role.v2:definition:" + digest([definition["path"], definition["start"], definition["end"], definition["model_identifier"], sources[definition["path"]]["sha256"]])[:24]
        definition["node_id"] = identity
        source = sources[definition["path"]]
        text = "\n".join(source["lines"][definition["start"]-1:definition["end"]])
        nodes[identity] = {"id": identity, "kind": "document_unit", "label": "manual model " + definition["title"],
                           "path": definition["path"], "parent": None, "role": " / ".join(definition["ancestors"]),
                           "value": definition["model_identifier"], "search_text": text,
                           "scope": {"case_directory": None, "physical_file": definition["path"], "source_version": source["sha256"]},
                           "evidence": [{"path": definition["path"], "start": definition["start"], "end": definition["end"], "source_sha256": source["sha256"]}],
                           "conditions": definition["conditions"], "effective_state": "not_evaluated", "status": "literal_public_manual_section"}
    # 全部历史教程—手册边另存继承清单；避免旧的未充分角色审计连接作为旁路。
    removed, retained = [], []
    for edge in graph["edges"]:
        kinds = {nodes[edge[k]]["path"].split("/", 1)[0] for k in ("source", "target")}
        if kinds == {"tutorials", "manual"}:
            removed.append(edge)
        else:
            retained.append(edge)
    edges, unresolved, counts = [], [], Counter()
    # 仅构图时局部按模型名分组，不保存或加载为检索索引。
    by_identifier = {}
    for definition in definitions:
        by_identifier.setdefault(definition["model_identifier"].casefold(), []).append(definition)
    for node in list(nodes.values()):
        if node["kind"] != "configuration" or not node["path"].startswith("tutorials/"):
            continue
        key = str(node.get("key") or "")
        if key.casefold() in {"format", "class", "version", "location", "object", "name", "file"}:
            continue
        value = str(node.get("value") or "").strip().strip('"')
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_+.-]*)(\s*\([^\n]*\))?", value)
        if not match or match[1].casefold() not in by_identifier:
            continue
        role = key
        if key == "type":
            parts = str(node.get("dictionary") or "").split("/")
            role = parts[-2] if len(parts) >= 2 else ""
        candidates = by_identifier[match[1].casefold()]
        aligned = [d for d in candidates if compatible(role, d["role_context"], key=key)]
        if len(aligned) != 1:
            unresolved.append({"node_id": node["id"], "dictionary": node.get("dictionary"), "value": value,
                               "reason": "ambiguous_role_aligned_definitions" if len(aligned) > 1 else "role_not_supported_by_public_context",
                               "candidate_definition_nodes": [d["node_id"] for d in candidates], "role_aligned_nodes": [d["node_id"] for d in aligned]})
            continue
        definition = aligned[0]
        instance_evidence = node.get("evidence", [])
        target = nodes[definition["node_id"]]
        identity = "principia.role.v1:edge:" + digest([node["id"], target["id"], "DOCUMENTED_BY"])[:24]
        edge = {"id": identity, "relation": "DOCUMENTED_BY", "source": node["id"], "target": target["id"],
                "cross_source": True, "scope": node.get("scope", {}), "instance_evidence": instance_evidence,
                "definition_evidence": target["evidence"], "evidence": instance_evidence+target["evidence"],
                "conditions": definition["conditions"], "condition_satisfied": None,
                "status": "exact_declared_identifier_with_public_role_context", "role_match": {"configuration_role": role, "manual_context": definition["role_context"]},
                "configured_value": value, "configured_arguments": match[2],
                "limits": "只支持声明身份与文档角色对应，不证明手册物理条件满足、参数实现匹配、include已展开或运行成功。"}
        edges.append(edge)
        counts[role] += 1
    graph["edges"] = retained + edges
    graph["role_alignment_revision"] = {"schema": "public-role-alignment-v2", "base_graph_sha256": digest(original_bytes),
         "new_llm_calls": 0, "inherited_semantic_model": "deepseek-flash", "inherited_cold_build_cost": "not_reconstructed",
         "construction_policy": "public manual hierarchy and exact configuration declarations only; no dataset/gold or retrieval index"}
    source_checks = 0
    for node in nodes.values():
        for anchor in node.get("evidence", []):
            source = sources[anchor["path"]]
            if not 1 <= anchor["start"] <= anchor["end"] <= len(source["lines"]):
                raise ValueError("graph anchor outside authoritative source")
            if anchor.get("source_sha256") and anchor["source_sha256"] != source["sha256"]:
                raise ValueError("graph anchor hash drift")
            source_checks += 1
    if any(len({a["path"].split("/", 1)[0] for a in n.get("evidence", [])}) > 1 for n in nodes.values()):
        raise ValueError("cross-source bundled node would confound edge ablation")
    args.output.mkdir(parents=True)
    graph_path = args.output / "principia-graph.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, sort_keys=True)+"\n")
    manifest = {"schema": "public-role-graph-construction-v1", "implementation_sha256": digest(Path(__file__).read_bytes()),
          "guard_implementation_sha256": digest((Path(__file__).parent/"chapter2_production_guard.py").read_bytes()),
          "base_graph_sha256": digest(original_bytes), "graph_sha256": digest(graph_path.read_bytes()), "new_llm_calls": 0,
          "inherited_semantic_model": "deepseek-flash", "source_files": {p: s["sha256"] for p, s in sources.items()},
          "model_definition_nodes": len(definitions), "new_cross_source_edges": len(edges), "removed_legacy_cross_edges": len(removed),
          "role_edge_counts": dict(counts), "unresolved": unresolved, "node_anchor_checks": source_checks,
          "nodes": len(nodes), "edges": len(graph["edges"]), "cross_source_bundled_nodes": 0,
          "guard": guard, "construction_seconds": time.monotonic()-started,
          "limits": "只测本次确定性图增强，不是历史完整冷构图成本。词面角色可漏连或误连，后续开发审查语义；歧义未强行连接。运行条件未求值。"}
    (args.output / "construction-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    (args.output / "principia-graph-validation.json").write_text(json.dumps({"status": "passed", "graph_sha256": manifest["graph_sha256"],
          "checks": "node anchors/source hashes/no cross-bundled nodes", "semantic_correctness_proven": False}, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({k: manifest[k] for k in ("nodes", "edges", "model_definition_nodes", "new_cross_source_edges", "removed_legacy_cross_edges", "node_anchor_checks", "new_llm_calls", "construction_seconds")}))


if __name__ == "__main__":
    main()
