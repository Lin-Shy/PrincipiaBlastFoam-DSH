"""窄范围、双侧原文支持的 function-object 对齐；不读取问题或答案。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re
import time

if __package__:
    from . import graphify_structure as structure
else:
    import graphify_structure as structure

encoded, sha = structure.encoded, structure.sha
SCHEMA = "principia-conditional-cross-source-v1"
MANUAL = "manual/markdown/15_function_objects.md"
KINDS = {"SELECTOR_DOCUMENTED_BY", "PARAMETER_DOCUMENTED_BY"}
RULE = {"manual": MANUAL, "role": "function_object", "file_name": "controlDict",
        "selector_components": ["functions", "<literal-instance>", "type"],
        "parameter_scope": "direct_child_of_same_physical_instance",
        "name_matching": "exact_primary_heading_name_no_automatic_aliases",
        "claims": "literal_configuration_documentation_alignment_not_runtime_activation"}


def identity(kind, *parts):
    return "principia.cross.v1:" + kind + ":" + sha(encoded(parts))[:24]


def anchor(raw, path, start, end, role):
    lines = raw[path].decode().splitlines(keepends=True)
    if not 1 <= start <= end <= len(lines):
        raise ValueError("cross-source anchor out of bounds")
    text = "".join(lines[start - 1:end])
    return {"path": path, "start": start, "end": end, "source_sha256": sha(raw[path]),
            "quote_sha256": sha(text.encode()), "role": role}


def definitions(raw, nodes):
    """Keep complete model sections: conditions/formulas are not sentence-clipped."""
    lines = raw[MANUAL].decode().splitlines(keepends=True)
    headings = [(i, re.fullmatch(r"## 15\.\d+ (.+)", line.strip()))
                for i, line in enumerate(lines) if line.startswith("## ")]
    if not headings or not all(m for _, m in headings):
        raise ValueError("function-object chapter heading grammar changed")
    intro = "".join(lines[:headings[0][0]])
    if not all(t in intro for t in ("function objects", "controlDict", "functions", "type", "impulse;")):
        raise ValueError("manual function-object role/selector evidence unavailable")
    role = anchor(raw, MANUAL, 1, headings[0][0], "manual_role_and_selector_example")
    byline = {n["metadata"].get("hierarchy", [""])[-1]: n for n in nodes.values()
              if n.get("structure_kind") == "section" and n["source_file"] == MANUAL}
    result, skipped = {}, []
    for index, (start, match) in enumerate(headings):
        title = match[1]
        # A parenthetical alternate name is not silently treated as a proven alias.
        name_match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)(?: \([^()]+\))?", title)
        if not name_match:
            skipped.append({"path": MANUAL, "line": start + 1, "reason": "non_primary_model_heading", "title": title})
            continue
        name = name_match[1]
        end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        full_title = lines[start].strip().removeprefix("## ")
        if full_title not in byline:
            raise ValueError("definition has no structural section endpoint")
        section = byline[full_title]
        location = re.fullmatch(r"L(\d+)(?:-L(\d+))?", section["source_location"])
        if not location or int(location[1]) != start + 1:
            raise ValueError("manual section endpoint line mismatch")
        did = identity("definition", section["observation_id"], RULE["role"], name)
        params, inside_table = {}, False
        for offset in range(start + 1, end):
            row = lines[offset].strip()
            if row == "| Entry | Description |":
                inside_table = True
                continue
            if not row.startswith("|"):
                inside_table = False
                continue
            if not inside_table:
                continue
            cells = [c.strip() for c in row.strip("|").split("|")]
            key = re.fullmatch(r"`?([A-Za-z_][A-Za-z0-9_]*)`?", cells[0]) if len(cells) == 2 else None
            if not key:
                continue
            key = key[1]
            if key in params:
                raise ValueError("ambiguous repeated manual parameter")
            params[key] = {"key": key, "description_verbatim": cells[1],
                "evidence": anchor(raw, MANUAL, offset + 1, offset + 1, "manual_parameter_row"),
                "normalized_default_or_obligation": None}
        result[did] = {"id": did, "name": name, "role": RULE["role"],
            "section_node": section["id"], "corpus_id": section["corpus_id"],
            "evidence": [role, anchor(raw, MANUAL, start + 1, end, "complete_model_section")],
            "parameters": params, "evidence_status": "manual_literal_section",
            "condition_interpretation": "verbatim_section_retained_not_automatically_satisfied"}
    if len({d["name"] for d in result.values()}) != len(result):
        raise ValueError("ambiguous primary manual name")
    return result, skipped


def node_anchor(raw, node, role, header=False):
    m = node["metadata"]
    return anchor(raw, node["source_file"], m["line_start"],
                  m["open_line"] if header else m["line_end"], role)


def derive(graph, raw, structure_id):
    nodes = {n["id"]: n for n in graph["nodes"] if n.get("_origin") == "principia_deterministic_structure"}
    docs, candidates = definitions(raw, nodes)
    byname = {d["name"]: d for d in docs.values()}
    children, byfile = defaultdict(list), defaultdict(list)
    for n in nodes.values():
        if "parent_node" in n["metadata"]:
            children[n["metadata"]["parent_node"]].append(n)
            byfile[n["source_file"]].append(n)
    relations, inspected = [], Counter()

    def reject(node, reason):
        candidates.append({"node": node["id"], "path": node["source_file"],
            "dictionary_path": node["metadata"]["dictionary_path"], "reason": reason,
            "evidence_status": "not_aligned", "not_a_verified_relation": True})

    def emit(kind, target, selector, model, ancestors, enabled, parameter=None):
        evidence = [node_anchor(raw, n, "tutorial_parent_header", True) for n in ancestors]
        evidence.append(node_anchor(raw, selector, "tutorial_literal_selector"))
        if target["id"] != selector["id"]:
            evidence.append(node_anchor(raw, target, "tutorial_parameter_instance"))
        evidence.extend(node_anchor(raw, n, "tutorial_explicit_enabled") for n in enabled)
        manual_evidence = list(model["evidence"])
        if parameter:
            manual_evidence.append(parameter["evidence"])
        relations.append({"id": identity("relation", kind, target["observation_id"], model["id"]),
            "relation": kind, "source": target["id"], "target": model["id"],
            "selector_node": selector["id"], "instance_node": ancestors[-1]["id"],
            "parameter": parameter["key"] if parameter else None,
            "scope": deepcopy(target["scope"]), "manual_evidence": manual_evidence, "tutorial_evidence": evidence,
            "conditions": {"exact_primary_model_name": model["name"],
                "physical_file_name": "controlDict", "selector_path": selector["metadata"]["dictionary_path"],
                "same_physical_instance": ancestors[-1]["id"], "unresolved_selector_or_ancestor_flags": [],
                "parameter_direct_child": parameter is not None},
            "enabled_observations": [{"node": n["id"], "literal": n["metadata"]["value_text"],
                                      "flags": n["metadata"]["flags"]} for n in enabled],
            "evidence_status": "dual_source_literal_alignment",
            "confidence_scope": "exact_name_role_and_physical_path_only",
            "runtime_activation": "not_evaluated", "manual_preconditions_satisfied": "not_evaluated",
            "instance_value_is_default": False, "cooccurrence_is_dependency": False})

    for selector in sorted(nodes.values(), key=lambda n: n["id"]):
        m = selector["metadata"]
        parts = m.get("components", [])
        if selector.get("structure_kind") != "configuration" or PurePosixPath(selector["source_file"]).name != "controlDict":
            continue
        if len(parts) != 3 or parts[0] != "functions" or parts[-1] != "type":
            continue
        inspected["selectors_considered"] += 1
        if m["flags"]:
            reject(selector, "unresolved_selector_or_ancestor")
            continue
        model = byname.get(m["value_text"])
        if not model:
            reject(selector, "no_exact_primary_manual_definition")
            continue
        parent = nodes[m["parent_node"]]
        outer = nodes[parent["metadata"]["parent_node"]]
        if parent["structure_kind"] != "dictionary" or outer["structure_kind"] != "dictionary":
            raise ValueError("selector not inside two physical dictionaries")
        blockers = []
        for other in byfile[selector["source_file"]]:
            inspected["scope_barrier_node_visits"] += 1
            op = other["metadata"]["components"][:-1]
            if other["structure_kind"] in ("directive", "unresolved_statement") and parts[:len(op)] == op:
                blockers.append(other["id"])
        if blockers:
            reject(selector, "ancestor_scope_contains_unevaluated_directive_or_statement")
            continue
        siblings = children[parent["id"]]
        enabled = [n for n in siblings if n["metadata"]["key"] == "enabled" and "value_text" in n["metadata"]]
        emit("SELECTOR_DOCUMENTED_BY", selector, selector, model, [outer, parent], enabled)
        for node in sorted(siblings, key=lambda n: n["id"]):
            inspected["parameter_sibling_visits"] += 1
            param = model["parameters"].get(node["metadata"]["key"])
            if not param or node["structure_kind"] != "configuration":
                continue
            if node["metadata"]["flags"]:
                reject(node, "unresolved_parameter_literal")
                continue
            emit("PARAMETER_DOCUMENTED_BY", node, selector, model, [outer, parent], enabled, param)
    return {"schema": SCHEMA, "structure_id": structure_id, "rule": deepcopy(RULE),
        "definitions": docs, "relations": sorted(relations, key=lambda r: r["id"]),
        "candidates": sorted(candidates, key=lambda r: encoded(r)), "work": dict(inspected),
        "limitations": ["Only function-object exact primary names and literal direct Entry keys are aligned.",
            "No alias, dependency, runtime activation, include expansion or general default is inferred.",
            "All manual section qualifications are retained; physical/field applicability is not certified.",
            "Original Graphify inferred relations are not consumed or upgraded by this layer."]}


def validate(layer, graph, raw, structure_id):
    checked, characters = 0, 0
    nodes = {n["id"]: n for n in graph["nodes"]}
    for relation in layer["relations"]:
        if relation["relation"] not in KINDS:
            raise ValueError("undeclared cross-source relation")
        if not relation["manual_evidence"] or not relation["tutorial_evidence"]:
            raise ValueError("one-sided cross-source evidence")
        target = nodes[relation["source"]]
        for side, category in (("manual_evidence", "manual"), ("tutorial_evidence", "tutorial")):
            for a in relation[side]:
                if structure.source_category(a["path"]) != category:
                    raise ValueError("wrong evidence source category")
                actual = anchor(raw, a["path"], a["start"], a["end"], a["role"])
                if actual != a:
                    raise ValueError("cross-source evidence hash drift")
                if category == "tutorial" and a["path"] != target["source_file"]:
                    raise ValueError("cross-instance source evidence")
                checked += 1
                characters += len("".join(raw[a["path"]].decode().splitlines(keepends=True)[a["start"] - 1:a["end"]]))
    # Recheck all conditions and completeness, not only the count of accepted edges.
    if layer != derive(graph, raw, structure_id):
        raise ValueError("alignment rule, conditions, endpoints or completeness mismatch")
    return {"status": "PASS", "anchors_checked_with_repetition": checked,
            "anchor_characters_checked_with_repetition": characters,
            "condition_derivation_rechecks": 1, "not_a_human_semantic_accuracy_estimate": True}


def load_structure(path):
    reads = Counter()

    def read(file):
        raw = file.read_bytes()
        reads["explicit_read_operations"] += 1
        reads["explicit_read_bytes"] += len(raw)
        return raw

    manifest_raw = read(path / "manifest.json")
    manifest = json.loads(manifest_raw)
    products = {}
    for name in ("GH/graph.json", "source_index.json", "corpus_manifest.json"):
        content = read(path / name)
        if sha(content) != manifest["artifacts"][name]:
            raise ValueError("structural artifact identity drift: " + name)
        products[name] = json.loads(content)
    corpus = Path(manifest["corpus_root"]).resolve()
    inventory = products["source_index.json"]["inventory"]
    if {p.relative_to(corpus).as_posix() for p in corpus.rglob("*") if p.is_file()} != set(inventory):
        raise ValueError("corpus inventory drift")
    raw = {}
    for p, row in inventory.items():
        file = (corpus / p).resolve()
        structure.source_category(p)
        if not file.is_relative_to(corpus):
            raise ValueError("source escapes corpus")
        raw[p] = read(file)
        if sha(raw[p]) != row["sha256"] or len(raw[p]) != row["bytes"]:
            raise ValueError("corpus byte drift")
    return manifest, sha(manifest_raw), products["GH/graph.json"], products["source_index.json"], raw, reads


def build(structure_path, output):
    if output.exists():
        raise FileExistsError("choose a fresh cross-source output directory")
    start = time.perf_counter()
    parent, parent_sha, graph, index, raw, reads = load_structure(structure_path)
    layer = derive(graph, raw, parent["construction_id"])
    validation = validate(layer, graph, raw, parent["construction_id"])
    code = {"graphify_cross_source.py": Path(__file__).read_bytes(),
            "graphify_structure.py": Path(structure.__file__).read_bytes(),
            "navigation_structure_parser.py": Path(structure.structural_parser.__file__).read_bytes()}
    reads["code_identity_read_operations"] = len(code)
    reads["code_identity_read_bytes"] = sum(map(len, code.values()))
    relation_id = sha(encoded({"schema": SCHEMA, "structure_manifest_sha256": parent_sha,
        "layer_sha256": sha(encoded(layer)), "code": {n: sha(b) for n, b in code.items()}}))
    stats = {"definitions": len(layer["definitions"]), "relations": len(layer["relations"]),
        "relation_types": dict(Counter(r["relation"] for r in layer["relations"])),
        "cases": len({r["scope"]["case_directory"] for r in layer["relations"]}),
        "candidate_reasons": dict(Counter(c["reason"] for c in layer["candidates"])),
        "work_per_derivation": layer["work"], "model_calls": 0, "QA_evaluated": False}
    products = {"layer.json": encoded(layer), "validation.json": encoded(validation), "stats.json": encoded(stats),
                **{"code/" + n: b for n, b in code.items()}}
    manifest = {"schema": SCHEMA, "relation_id": relation_id, "structure_root": str(structure_path),
        "structure_manifest_sha256": parent_sha, "construction_id": parent["construction_id"],
        "corpus_id": parent["corpus_id"], "artifacts": {n: sha(b) for n, b in products.items()},
        "model_calls": 0, "QA_evaluated": False}
    products["manifest.json"] = encoded(manifest)
    output.mkdir(parents=True)
    for name, content in products.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    accounting = {**reads, "wall_seconds_before_accounting_write": time.perf_counter() - start,
        "written_bytes_excluding_accounting": sum(map(len, products.values())), "derivation_passes": 2,
        "validation": validation, "model_requests": 0, "model_tokens": 0,
        "limits": "Explicit reads and total command wall only; repeated full-file decode/split CPU work in anchor helpers is included in wall but not separately counted. Imports/OS I/O and development/review not fully measured. Character work overlaps; not API tokens."}
    (output / "accounting.json").write_bytes(encoded(accounting))
    print(json.dumps({"relation_id": relation_id, **stats, "validation": validation["status"]}))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--structure", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    build(args.structure.resolve(), args.output.resolve())
