"""从冻结原始语料构建独立物理图；可选 Graphify 父图只用于历史消融。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import time

if __package__:
    from . import navigation_structure_parser as structural_parser
else:
    import navigation_structure_parser as structural_parser


SCHEMA = "graphify-physical-structure-v1"
PREFIX = "principia.structure.v1:"
RELATIONS = {"HAS_DIRECTORY", "HAS_FILE", "HAS_SECTION", "HAS_UNIT", "HAS_BLOCK", "HAS_ENTRY",
             "HAS_DIRECTIVE", "HAS_UNRESOLVED_STATEMENT", "SAME_SOURCE_FILE"}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identifier(kind, *parts):
    return PREFIX + kind + ":" + sha(encoded(parts))[:24]


def source_category(path):
    if path.startswith("/") or posixpath.normpath(path) != path:
        raise ValueError("non-canonical source path")
    if path.startswith("manual/markdown/"):
        return "manual"
    if path.startswith("tutorials/"):
        return "tutorial"
    raise ValueError("outside the two original corpus sources: " + path)


def load_support(path):
    modules, hashes = {}, {}
    for name in ("knowledge", "manual_graph"):
        file = path / (name + ".py")
        raw = file.read_bytes()
        hashes[file.name] = sha(raw)
        spec = importlib.util.spec_from_file_location("structure_support_" + name + hashes[file.name][:8], file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules, hashes


class Projection:
    def __init__(self, raw, corpus_id):
        self.raw, self.corpus_id = raw, corpus_id
        self.hashes = {p: sha(r) for p, r in raw.items()}
        self.texts = {}
        for path, content in raw.items():
            try:
                text = content.decode("utf-8")
            except UnicodeError:
                continue
            if "\x00" not in text:
                self.texts[path] = text
        self.lines = {p: t.splitlines(keepends=True) for p, t in self.texts.items()}
        self.offsets = {p: [0] for p in self.texts}
        for p, lines in self.lines.items():
            for line in lines:
                self.offsets[p].append(self.offsets[p][-1] + len(line))
        self.nodes, self.links, self.spans, self.issues = {}, [], {}, []
        self.files, self.directories = {}, {}
        self.counts = Counter()
        self.coverage = {}
        self.control_roots = {p.removesuffix("/system/controlDict") for p in raw if p.endswith("/system/controlDict")}
        self.script_roots = {str(PurePosixPath(p).parent) for p in raw if PurePosixPath(p).name == "Allrun"}

    def span(self, path, start=None, end=None):
        if start is None:
            sid = identifier("inventory", path)
            if sid in self.spans:
                return sid
            self.spans[sid] = {"kind": "inventory_membership", "path": path, "sha256": self.hashes[path],
                               "bytes": len(self.raw[path])}
            return sid
        if not (1 <= start <= end <= len(self.lines[path])):
            raise ValueError("source span out of range: " + path)
        sid = identifier("span", path, start, end)
        if sid in self.spans:
            return sid
        raw = "".join(self.lines[path][start - 1:end])
        self.spans[sid] = {"kind": "original_text_lines", "path": path, "sha256": self.hashes[path],
            "line_start": start, "line_end": end, "quote_sha256": sha(raw.encode()),
            "start_offset": self.offsets[path][start - 1], "end_offset": self.offsets[path][end]}
        return sid

    def scope(self, path):
        roots = [c for c in self.control_roots if path.startswith(c + "/")]
        marker = "system/controlDict"
        if not roots:
            roots = [c for c in self.script_roots if path.startswith(c + "/")]
            marker = "Allrun_directory_candidate"
        case = max(roots, key=len) if roots else None
        relative = path[len(case) + 1:] if case else path
        parts = relative.split("/")
        return {"physical_file": path, "case_directory": case, "case_marker": marker if case else None,
            "corpus_version": self.corpus_id, "source_version": self.hashes[path],
            "case_relative_file": relative if case else None,
            "time_directory_hint": parts[0] if case and re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?|0\.orig)", parts[0]) else None,
            "top_level_tutorial_directory": path.split("/")[1] if path.startswith("tutorials/") else None,
            "region_directory_hint": parts[1] if len(parts) > 2 and parts[0] in ("0", "0.orig", "system", "constant") else None,
            "field_file_hint": parts[-1] if parts[0] in ("0", "0.orig") else None,
            "scope_claim": "physical_directory_and_dictionary_nesting_not_effective_runtime_scope"}

    def node(self, kind, label, path, *, start=None, end=None, identity=None, raw="", state="static", extra=None):
        nid = identifier(kind, path, identity if identity is not None else [start, end])
        if nid in self.nodes:
            raise ValueError("duplicate derived node identity")
        label = re.sub(r"\s+", " ", label).strip()
        evidence = self.span(path, start, end)
        node = {"id": nid, "label": f"{kind} {label} [{state}]", "source_file": path,
            "source_location": f"L{start}" + (f"-L{end}" if end != start else "") if start is not None else "",
            "_origin": "principia_deterministic_structure", "source_category": source_category(path),
            "structure_kind": kind, "source_sha256": self.hashes[path], "corpus_id": self.corpus_id,
            "extraction_method": SCHEMA, "evidence_status": state, "confidence_score": 1.0,
            "confidence_scope": "source_location_and_literal_physical_structure_only_not_execution_or_physical_validity",
            "source_span_ids": [evidence], "scope": self.scope(path), "rationale": raw,
            "metadata": extra or {}}
        if node["source_category"] == "tutorial":
            node["is_general_default"] = False
        self.nodes[nid] = node
        node["observation_id"] = identifier("observation", self.corpus_id, self.hashes[path], nid)
        return nid

    def edge(self, parent, child, relation, evidence=None):
        if relation not in RELATIONS:
            raise ValueError("undeclared construction factor")
        node = self.nodes[child] if child in self.nodes else self.nodes[parent]
        refs = evidence or node["source_span_ids"]
        source = self.spans[refs[0]]
        self.links.append({"source": parent, "target": child, "relation": relation,
            "_origin": "principia_deterministic_structure", "confidence": "PHYSICAL_STRUCTURE",
            "confidence_score": 1.0, "context": "physical_membership_not_runtime_dependency",
            "source_file": source["path"], "source_location": f"L{source['line_start']}" if "line_start" in source else "",
            "source_span_ids": list(refs), "evidence_status": "literal_source_or_inventory_membership",
            "confidence_scope": "source_or_directory_identity_only", "weight": 1.0})

    def inventory_nodes(self):
        witnesses = defaultdict(list)
        for path in sorted(self.raw):
            for parent in PurePosixPath(path).parents:
                if str(parent) != ".":
                    witnesses[str(parent)].append(path)
        for directory, paths in sorted(witnesses.items()):
            # There is no shared synthetic corpus root connecting manual/tutorial.
            anchor = next((p for p in paths if p == directory + "/system/controlDict"),
                          next((p for p in paths if p == directory + "/Allrun"), paths[0]))
            kind = ("case_directory" if directory in self.control_roots else
                    "script_directory" if directory in self.script_roots else "directory")
            nid = self.node(kind, directory, anchor, identity=directory, state="inventory",
                            extra={"directory": directory, "witness_file": anchor, "not_an_execution_dependency": True})
            # The witness is provenance, not the scope of the directory itself.
            # E.g. tutorials/ is not inside the first case in its inventory.
            roots = [c for c in self.control_roots if directory == c or directory.startswith(c + "/")]
            marker = "system/controlDict"
            if not roots:
                roots = [c for c in self.script_roots if directory == c or directory.startswith(c + "/")]
                marker = "Allrun_directory_candidate"
            case = max(roots, key=len) if roots else None
            self.nodes[nid]["scope"].update(physical_directory=directory, case_directory=case,
                case_marker=marker if case else None, case_relative_file=None,
                region_directory_hint=None, field_file_hint=None, time_directory_hint=None,
                scope_claim="directory_identity_with_file_as_inventory_witness_not_scope_owner")
            self.directories[directory] = nid
        for directory, nid in sorted(self.directories.items()):
            parent = str(PurePosixPath(directory).parent)
            if parent in self.directories:
                self.edge(self.directories[parent], nid, "HAS_DIRECTORY")
        for path in sorted(self.raw):
            text = self.texts.get(path)
            state = "source-file" if text is not None else "not-parsed"
            nid = self.node("file", path, path, start=1 if self.lines.get(path) else None,
                end=1 if self.lines.get(path) else None, identity=path, state=state,
                extra={"utf8_non_nul": text is not None, "bytes": len(self.raw[path]),
                       "image_pixels_understood": False, "file_was_executed": False})
            self.files[path] = nid
            self.coverage[path] = {"file_node": nid, "mode": "pending_text" if text is not None else "inventory_only",
                "semantic_completeness_claimed": False, "bytes": len(self.raw[path])}
            self.edge(self.directories[str(PurePosixPath(path).parent)], nid, "HAS_FILE", [self.span(path)])

    def markdown(self, path, manual):
        lines = self.lines[path]
        try:
            blocks = manual.atoms(lines)
        except ValueError as exc:
            # Preserve malformed input, not a repaired or silently omitted document.
            # This catch precedes node creation; implementation/coverage errors below
            # must still fail the build instead of publishing a partial hierarchy.
            self.issues.append({"path": path, "reason": "markdown_format_unparsed", "detail": str(exc)})
            self.other_text(path, state="unparsed-format")
            self.coverage[path]["mode"] = "markdown_raw_fallback"
            self.coverage[path]["diagnostic"] = str(exc)
            return
        stack, pending, parent, hierarchy = [], [], self.files[path], []
        ordinal = Counter()

        def flush():
            for group in manual.evidence_groups(pending, lines):
                a, z = group[0]["start"] + 1, group[-1]["end"]
                raw = "".join(lines[a - 1:z])
                kinds = sorted({b["kind"] for b in group})
                ordinal[parent] += 1
                label = (hierarchy[-1] if hierarchy else PurePosixPath(path).name) + " · " + "/".join(kinds) + " " + str(ordinal[parent])
                nid = self.node("document_unit", label, path, start=a, end=z, raw=raw, state="literal-text",
                    extra={"hierarchy": list(hierarchy), "block_kinds": kinds, "section": parent,
                           "meaning_defaults_and_conditions_not_automatically_interpreted": True})
                self.edge(parent, nid, "HAS_UNIT")
                self.counts["markdown_unit_characters"] += len(raw)

        for block in blocks:
            if block["kind"] != "heading":
                pending.append(block)
                continue
            flush()
            pending = []
            heading = lines[block["start"]].rstrip("\r\n")
            match = re.match(r"^(#{1,6})\s+(.+)", heading)
            level, title = len(match[1]), match[2]
            while stack and stack[-1][0] >= level:
                stack.pop()
            owner = stack[-1][1] if stack else self.files[path]
            hierarchy = [x[2] for x in stack] + [title]
            nid = self.node("section", " / ".join(hierarchy), path, start=block["start"] + 1,
                end=block["end"], raw="".join(lines[block["start"]:block["end"]]), state="literal-heading",
                extra={"heading_level": level, "hierarchy": list(hierarchy), "parent_section": owner})
            self.edge(owner, nid, "HAS_SECTION")
            stack.append((level, nid, title))
            parent = nid
        flush()
        rebuilt = "".join("".join(lines[b["start"]:b["end"]]) for b in blocks)
        if rebuilt != self.texts[path]:
            raise ValueError("Markdown atom coverage mismatch: " + path)
        self.coverage[path]["mode"] = "markdown_structure"
        self.coverage[path]["atom_characters_checked"] = len(rebuilt)

    def dictionaries(self, knowledge):
        parsed, queue, reached = {}, [], defaultdict(list)
        for path, text in sorted(self.texts.items()):
            name = PurePosixPath(path).name
            if not path.startswith("tutorials/") or path.endswith(".md"):
                continue
            if name.startswith(("Allrun", "Allclean")) or text.startswith("#!"):
                continue
            stream = knowledge.lex(text)
            self.counts["dictionary_detection_characters_lexed"] += len(text)
            root_header = len(stream) >= 2 and stream[0][0] == "FoamFile" and stream[1][0] == "{"
            if root_header or name.endswith(("Dict", "Properties")):
                queue.append(path)
        while queue:
            path = queue.pop(0)
            if path in parsed:
                continue
            result = structural_parser.dictionary(self.texts[path], knowledge.lex)
            parsed[path] = result
            self.counts["dictionary_characters_parsed"] += len(self.texts[path])
            for row in result["records"]:
                if row["kind"] != "directive" or row["key"] not in ("#include", "#includeIfPresent"):
                    continue
                argument = row["argument_text"]
                if re.fullmatch(r'"[^"$#<>]+"', argument):
                    argument = argument[1:-1]
                elif not re.fullmatch(r"[A-Za-z0-9_./-]+", argument):
                    continue
                target = posixpath.normpath(posixpath.join(str(PurePosixPath(path).parent), argument))
                if target.startswith("/") or target not in self.texts or not target.startswith("tutorials/"):
                    self.issues.append({"path": path, "line": row["line_start"], "reason": "literal_include_target_unavailable", "target": argument})
                    continue
                reached[target].append({"path": path, "line": row["line_start"],
                    "status": "literal_include_reachability_not_activation_or_effective_scope"})
                if target not in parsed:
                    queue.append(target)
        for path, result in sorted(parsed.items()):
            self.issues.extend({"path": path, **issue} for issue in result["issues"])
            mapped = {}
            for row in result["records"]:
                kind = {"block": "dictionary", "entry": "configuration", "directive": "directive",
                        "unresolved_statement": "unresolved_statement"}[row["kind"]]
                metadata = {k: copy.deepcopy(v) for k, v in row.items() if k not in ("raw", "ordinal", "parent")}
                metadata["include_reached_from"] = reached.get(path, [])
                metadata["effective_value_or_override_resolution"] = False
                state = "unresolved" if row["flags"] else "physical-only"
                raw = row["raw"] if row["kind"] != "block" else self.texts[path][row["start_offset"]:row["header_end_offset"]]
                nid = self.node(kind, row["dictionary_path"], path, start=row["line_start"], end=row["line_end"],
                    identity=[row["kind"], row["start_offset"]], raw=raw, state=state, extra=metadata)
                mapped[row["ordinal"]] = nid
                owner = mapped[row["parent"]] if row["parent"] is not None else self.files[path]
                self.nodes[nid]["metadata"]["parent_node"] = owner
                self.nodes[nid]["scope"]["physical_dictionary_components"] = copy.deepcopy(row["physical_components"])
                self.nodes[nid]["scope"]["phase_identity"] = "not_inferred_from_bare_block_name"
                relation = {"block": "HAS_BLOCK", "entry": "HAS_ENTRY", "directive": "HAS_DIRECTIVE",
                            "unresolved_statement": "HAS_UNRESOLVED_STATEMENT"}[row["kind"]]
                evidence = list(self.nodes[nid]["source_span_ids"])
                if row["parent"] is not None:
                    parent = result["records"][row["parent"]]
                    evidence.append(self.span(path, parent["line_start"], parent["open_line"]))
                self.edge(owner, nid, relation, evidence)
            self.coverage[path].update(mode="static_dictionary", records=len(result["records"]),
                unresolved_records=sum(bool(r["flags"]) for r in result["records"]),
                parser_issues=len(result["issues"]))
        self.counts["dictionary_files"] = len(parsed)
        self.counts["literal_include_target_files"] = len(reached)
        return set(parsed)

    def other_text(self, path, state="literal-text"):
        lines = self.lines[path]
        for a in range(0, len(lines), 48):
            z = min(a + 48, len(lines))
            raw = "".join(lines[a:z])
            nid = self.node("source_span", PurePosixPath(path).name + f" · {a + 1}-{z}", path,
                start=a + 1, end=z, raw=raw, state=state,
                extra={"execution_or_domain_interpretation": False})
            self.edge(self.files[path], nid, "HAS_UNIT")
            self.counts["other_text_span_characters"] += len(raw)
        self.coverage[path]["mode"] = "raw_text_spans" if lines else "empty_text"


def construct(raw, corpus_id, parent, support):
    projection = Projection(raw, corpus_id)
    projection.inventory_nodes()
    dictionaries = projection.dictionaries(support["knowledge"])
    for path in sorted(projection.texts):
        if path in dictionaries:
            continue
        if path.endswith(".md"):
            projection.markdown(path, support["manual_graph"])
        else:
            projection.other_text(path)
    original_ids = {n["id"] for n in parent["nodes"]}
    if len(original_ids) != len(parent["nodes"]) or original_ids & set(projection.nodes):
        raise ValueError("node ID collision")
    for node in parent["nodes"]:
        path = node.get("source_file")
        if path in projection.files:
            projection.edge(node["id"], projection.files[path], "SAME_SOURCE_FILE", [projection.span(path)])
        else:
            projection.issues.append({"original_node": node["id"], "reason": "original_primary_source_not_resolved", "source_file": path})
    gn = copy.deepcopy(parent)
    gn["nodes"].extend(projection.nodes[n] for n in sorted(projection.nodes))
    gh = copy.deepcopy(gn)
    gh["links"].extend(sorted(projection.links, key=lambda e: (e["relation"], e["source"], e["target"])))
    source_index = {"schema": SCHEMA, "corpus_id": corpus_id,
        "inventory": {p: {"sha256": projection.hashes[p], "bytes": len(r), "source_category": source_category(p),
                           "text_lines": len(projection.lines[p]) if p in projection.lines else None} for p, r in sorted(raw.items())},
        "spans": projection.spans, "coverage": projection.coverage}
    stats = {"input_files": len(raw), "utf8_non_nul_files": len(projection.texts),
        "original_nodes": len(parent["nodes"]), "original_edges": len(parent["links"]),
        "added_nodes": len(projection.nodes), "added_edges_GH": len(projection.links),
        "node_kinds": dict(Counter(n["structure_kind"] for n in projection.nodes.values())),
        "new_evidence_statuses": dict(Counter(n["evidence_status"] for n in projection.nodes.values())),
        "edge_relations": dict(Counter(e["relation"] for e in projection.links)),
        "source_spans": len(projection.spans), "extraction_work": dict(projection.counts),
        "file_coverage_modes": dict(Counter(r["mode"] for r in projection.coverage.values())),
        "projection_source_bytes_fingerprinted": sum(map(len, raw.values())),
        "graph_deepcopy_node_records": len(parent["nodes"]) + len(gn["nodes"]),
        "graph_deepcopy_edge_records": 2 * len(parent["links"]),
        "limits": ["New nodes are deterministic navigation, not a QA answer cache.",
            "No new cross-source semantic or parameter alignment is claimed in this physical stage.",
            "No image understanding, dictionary execution, shell execution, include activation or override resolution.",
            "Repeated names/conditional branches/opaque list dictionaries and syntax uncertainty require original-source checking.",
            "New node status is visible in labels because native Graphify query omits arbitrary metadata."]}
    return gn, gh, source_index, projection.issues, stats


def validate(parent, gn, gh, source_index, raw):
    if gn["nodes"] != gh["nodes"] or gn["links"] != parent["links"]:
        raise ValueError("GN/GH node equality or GN edge invariance failed")
    if gn["nodes"][:len(parent["nodes"])] != parent["nodes"] or gh["links"][:len(parent["links"])] != parent["links"]:
        raise ValueError("original Graphify elements changed")
    if {k: v for k, v in gn.items() if k not in ("nodes", "links")} != {k: v for k, v in parent.items() if k not in ("nodes", "links")}:
        raise ValueError("original graph-level data changed")
    if {k: v for k, v in gh.items() if k not in ("nodes", "links")} != {k: v for k, v in gn.items() if k not in ("nodes", "links")}:
        raise ValueError("GN/GH graph-level metadata changed")
    nodes = {n["id"]: n for n in gh["nodes"]}
    if len(nodes) != len(gh["nodes"]):
        raise ValueError("duplicate graph node")
    if set(source_index["inventory"]) != set(raw) or set(source_index["coverage"]) != set(raw):
        raise ValueError("source coverage inventory incomplete")
    for path, row in source_index["coverage"].items():
        if row["mode"] == "pending_text" or nodes[row["file_node"]]["source_file"] != path:
            raise ValueError("unaccounted source coverage")
    spans = source_index["spans"]
    hashes = {p: sha(r) for p, r in raw.items()}
    texts = {}
    for p, r in raw.items():
        try:
            texts[p] = r.decode("utf-8")
        except UnicodeError:
            pass
    lines = {p: t.splitlines(keepends=True) for p, t in texts.items()}
    originals = {}
    for span in spans.values():
        path = span["path"]
        if path not in raw or hashes[path] != span["sha256"]:
            raise ValueError("source identity mismatch")
        if span["kind"] == "original_text_lines":
            text = texts[path]
            if not 1 <= span["line_start"] <= span["line_end"] <= len(lines[path]):
                raise ValueError("source line interval out of bounds")
            actual = "".join(lines[path][span["line_start"] - 1:span["line_end"]])
            if sha(actual.encode()) != span["quote_sha256"] or text[span["start_offset"]:span["end_offset"]] != actual:
                raise ValueError("source line/offset anchor mismatch")
            originals[identifier("span", path, span["line_start"], span["line_end"])] = actual
    for node in gn["nodes"][len(parent["nodes"]):]:
        if not node["id"].startswith(PREFIX) or node["source_file"] not in raw:
            raise ValueError("derived node identity/source missing")
        if any(ref not in spans or spans[ref]["path"] != node["source_file"] for ref in node["source_span_ids"]):
            raise ValueError("derived node source span missing")
        first = spans[node["source_span_ids"][0]]
        expected_loc = (f"L{first['line_start']}" + (f"-L{first['line_end']}" if first['line_end'] != first['line_start'] else "")) if "line_start" in first else ""
        if node["source_location"] != expected_loc or node["source_sha256"] != hashes[node["source_file"]]:
            raise ValueError("visible node anchor differs from source index")
        if node["rationale"] and node["rationale"] not in originals.get(node["source_span_ids"][0], ""):
            raise ValueError("searchable rationale is not literal source text")
        if node["source_category"] != source_category(node["source_file"]) or node["corpus_id"] != source_index["corpus_id"]:
            raise ValueError("node source category/version mismatch")
        if node["scope"]["corpus_version"] != source_index["corpus_id"] or node["scope"]["source_version"] != hashes[node["source_file"]]:
            raise ValueError("scope version mismatch")
        if node["observation_id"] != identifier("observation", source_index["corpus_id"], hashes[node["source_file"]], node["id"]):
            raise ValueError("observation identity mismatch")
        directory = node["metadata"].get("directory")
        case = node["scope"]["case_directory"]
        if directory and case and not (directory == case or directory.startswith(case + "/")):
            raise ValueError("directory inherited scope of unrelated witness file")
    for edge in gh["links"][len(parent["links"]):]:
        if edge["relation"] not in RELATIONS or edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("invalid structural edge")
        if any(ref not in spans for ref in edge["source_span_ids"]):
            raise ValueError("edge source anchor missing")
        a, b = nodes[edge["source"]], nodes[edge["target"]]
        if edge["relation"] == "HAS_DIRECTORY":
            if str(PurePosixPath(b["metadata"]["directory"]).parent) != a["metadata"]["directory"]:
                raise ValueError("incorrect directory parent")
        if edge["relation"] == "HAS_FILE":
            if str(PurePosixPath(b["source_file"]).parent) != a["metadata"]["directory"]:
                raise ValueError("incorrect file parent")
        if edge["relation"] in {"HAS_BLOCK", "HAS_ENTRY", "HAS_DIRECTIVE", "HAS_UNRESOLVED_STATEMENT", "HAS_SECTION", "HAS_UNIT", "SAME_SOURCE_FILE"}:
            if a["source_file"] != b["source_file"]:
                raise ValueError("physical nesting crossed source files")
        if edge["relation"] in {"HAS_BLOCK", "HAS_ENTRY", "HAS_DIRECTIVE", "HAS_UNRESOLVED_STATEMENT"} and a.get("structure_kind") == "dictionary":
            am, bm = a["metadata"], b["metadata"]
            if not (am["line_start"] <= bm["line_start"] <= bm["line_end"] <= am["line_end"]):
                raise ValueError("child lies outside physical parent")
            if bm["parent_node"] != a["id"] or bm["physical_components"][:-1] != am["physical_components"]:
                raise ValueError("child dictionary components disagree with parent")
    return {"status": "PASS", "identical_GN_GH_nodes": len(gn["nodes"]), "original_nodes_unchanged": len(parent["nodes"]),
            "original_edges_unchanged": len(parent["links"]), "source_anchors_checked": len(spans),
            "source_bytes_fingerprinted": sum(map(len, raw.values())),
            "source_span_characters_checked": sum(map(len, originals.values())),
            "note": "Structural/source invariants, not semantic QA correctness or runtime parsing validation."}


def build(archive, output, support_path, parent_variant="none"):
    if output.exists():
        raise FileExistsError("preserve previous build; choose a new output directory")
    if parent_variant not in {"none", "native", "text_adapter"}:
        raise ValueError("parent_variant must be none, native or text_adapter")
    started = time.perf_counter()
    reads = Counter()

    def read(path, role):
        content = path.read_bytes()
        reads[role + "_read_operations"] += 1
        reads[role + "_read_bytes"] += len(content)
        return content

    manifest_raw = read(archive / "corpus_manifest.json", "manifest")
    manifest = json.loads(manifest_raw)
    if parent_variant == "none":
        summary = {"baseline_id": None}
        parent_raw = encoded({"nodes": [], "links": [], "source": "independent_principia_source_graph"})
    else:
        summary = json.loads(read(archive / parent_variant / "baseline_summary.json", "parent_identity"))
        parent_raw = read(archive / parent_variant / "graphify-out/graph.json", "parent_graph")
        if sha(parent_raw) != summary["artifacts"]["graph.json"]["sha256"] or summary["corpus_id"] != manifest["corpus_id"]:
            raise ValueError("frozen parent graph identity mismatch")
    identity_rows = [{k: r[k] for k in ("path", "sha256", "bytes")} for r in manifest["files"]]
    if sha(json.dumps(identity_rows, sort_keys=True, ensure_ascii=False).encode()) != manifest["corpus_id"]:
        raise ValueError("corpus identity does not match inventory")
    raw = {}
    corpus = (archive / "corpus_native").resolve()
    paths = {p.relative_to(corpus).as_posix() for p in corpus.rglob("*") if p.is_file()}
    if paths != {r["path"] for r in identity_rows} or len(paths) != len(identity_rows):
        raise ValueError("corpus file set drift")
    for row in identity_rows:
        path = (corpus / row["path"]).resolve()
        source_category(row["path"])
        if not path.is_relative_to(corpus):
            raise ValueError("source escapes corpus")
        content = read(path, "corpus")
        if sha(content) != row["sha256"] or len(content) != row["bytes"]:
            raise ValueError("corpus content drift: " + row["path"])
        raw[row["path"]] = content
    support, support_hashes = load_support(support_path)
    code = {"graphify_structure.py": read(Path(__file__), "implementation_identity"),
            "navigation_structure_parser.py": read(Path(structural_parser.__file__), "implementation_identity")}
    for name in support_hashes:
        code[name] = read(support_path / name, "support_freeze")
        if sha(code[name]) != support_hashes[name]:
            raise ValueError("support code changed during import")
    dependencies = {name: sha(content) for name, content in code.items()}
    parent = json.loads(parent_raw)
    gn, gh, index, issues, stats = construct(raw, manifest["corpus_id"], parent, support)
    checks = validate(parent, gn, gh, index, raw)
    identity = sha(encoded({"schema": SCHEMA, "corpus_id": manifest["corpus_id"],
                            "parent_graph_sha256": sha(parent_raw), "dependencies": dependencies}))
    products = {"GN/graph.json": encoded(gn), "GH/graph.json": encoded(gh), "source_index.json": encoded(index),
        "diagnostics.json": encoded(issues), "construction_stats.json": encoded(stats), "validation.json": encoded(checks),
        "parent_graph.json": parent_raw, "corpus_manifest.json": manifest_raw,
        **{"dependencies/" + name: content for name, content in code.items()}}
    frozen = {"schema": SCHEMA, "construction_id": identity, "parent_baseline_id": summary["baseline_id"],
        "parent_variant": parent_variant,
        "parent_graph_sha256": sha(parent_raw), "corpus_id": manifest["corpus_id"], "dependencies": dependencies,
        "variants": {"GN": {"nodes": len(gn["nodes"]), "edges": len(gn["links"])},
                     "GH": {"nodes": len(gh["nodes"]), "edges": len(gh["links"])}},
        "corpus_root": str(corpus), "artifacts": {name: sha(content) for name, content in products.items()},
        "model_calls": 0, "LLM_generated_new_relations": False, "QA_evaluated": False,
        "independent_of_graphify_graph": parent_variant == "none"}
    output.mkdir(parents=True)
    for name, content in products.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (output / "manifest.json").write_bytes(encoded(frozen))
    accounting = {"wall_seconds_before_accounting_write": time.perf_counter() - started,
        "explicit_read_operations_and_bytes": dict(reads), "support_import_identity_reads": len(support_hashes),
        "support_import_identity_read_bytes": sum(len(code[n]) for n in support_hashes),
        "written_artifacts_excluding_accounting": len(products) + 1,
        "written_bytes_excluding_accounting": sum(len(v) for v in products.values()) + len(encoded(frozen)),
        "in_memory_work_projections": stats["extraction_work"], "model_requests": 0, "model_tokens": 0,
        "limits": ["This accounts the deterministic construction; an optional parent baseline cost is separate.",
            "Import/interpreter/OS cache I/O is not fully traced; explicit corpus/identity reads and outputs are counted.",
            "Character projections overlap and are not additive API tokens; review/installation/preparation outside this command are separate."]}
    (output / "accounting.json").write_bytes(encoded(accounting))
    print(json.dumps({"output": str(output), "construction_id": identity, "variants": frozen["variants"],
                      "text_files": stats["utf8_non_nul_files"], "validation": checks["status"], "model_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--support-code", type=Path, required=True)
    parser.add_argument("--parent-variant", choices=("none", "native", "text_adapter"), default="none")
    args = parser.parse_args()
    build(args.archive.resolve(), args.output.resolve(), args.support_code.resolve(), args.parent_variant)
