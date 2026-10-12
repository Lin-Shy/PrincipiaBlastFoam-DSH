"""按物理作用域和已核验对齐组织完整证据组的离线检索原型。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import time

if __package__:
    from . import graphify_cross_source as cross
else:
    import graphify_cross_source as cross

SCHEMA = "principia-scoped-evidence-search-v1"
STOP = set("a an the to of in on for and or is are be with from how what where can use please".split())


def tokens(text):
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[\u4e00-\u9fff]+", text)
    split = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+", " ".join(words))
    return {w.casefold() for w in words + split if w.casefold() not in STOP}


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def short(kind, *parts):
    return kind + cross.sha(cross.encoded(parts))[:16]


class Engine:
    def __init__(self, graph, index, raw, layer, identity):
        start = time.perf_counter()
        self.identity, self.index, self.raw, self.layer = identity, index, raw, layer
        self.nodes = {n["id"]: n for n in graph["nodes"] if n.get("_origin") == "principia_deterministic_structure"}
        self.lines = {p: b.decode().splitlines(keepends=True) for p, b in raw.items()
                      if index["inventory"][p]["text_lines"] is not None}
        self.postings, self.node_terms = defaultdict(set), {}
        self.cases = sorted({n["scope"]["case_directory"] for n in self.nodes.values() if n["scope"]["case_directory"]})
        self.files = {n["source_file"]: n["id"] for n in self.nodes.values() if n["structure_kind"] == "file"}
        chars = 0
        for nid, n in self.nodes.items():
            m = n["metadata"]
            text = " ".join([n["label"], n["source_file"], n["rationale"], m.get("value_text", "")])
            chars += len(text)
            self.node_terms[nid] = tokens(text)
            for term in self.node_terms[nid]:
                self.postings[term].add(nid)
        self.clusters, self.node_clusters = defaultdict(list), defaultdict(set)
        for r in layer["relations"]:
            self.clusters[r["selector_node"]].append(r)
        attachment_visits = 0
        for selector, relations in self.clusters.items():
            model = layer["definitions"][relations[0]["target"]]
            related = {r["source"] for r in relations} | {selector, relations[0]["instance_node"], model["section_node"]}
            related.add(self.files[self.nodes[selector]["source_file"]])
            extent = next(a for a in model["evidence"] if a["role"] == "complete_model_section")
            for nid, node in self.nodes.items():
                attachment_visits += 1
                if node["structure_kind"] != "document_unit" or node["source_file"] != extent["path"]:
                    continue
                a = index["spans"][node["source_span_ids"][0]]
                if extent["start"] <= a.get("line_start", 0) <= a.get("line_end", 0) <= extent["end"]:
                    related.add(nid)
            for nid in related:
                self.node_clusters[nid].add(selector)
        self.initialization = {"indexed_nodes": len(self.nodes), "indexed_characters_with_repetition": chars,
            "posting_memberships": sum(map(len, self.postings.values())),
            "relation_attachment_node_visits": attachment_visits,
            "decoded_source_bytes": sum(len(raw[p]) for p in self.lines),
            "index_wall_seconds": time.perf_counter() - start, "model_calls": 0}

    @classmethod
    def load(cls, directory):
        start = time.perf_counter()
        manifest_raw = (directory / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        code_bytes = 0
        for module in (cross, cross.structure, cross.structure.structural_parser):
            name = Path(module.__file__).name
            content = Path(module.__file__).read_bytes()
            code_bytes += len(content)
            if cross.sha(content) != manifest["artifacts"]["code/" + name]:
                raise ValueError("loaded alignment/structure code differs from frozen relation layer")
        layer_raw = (directory / "layer.json").read_bytes()
        if cross.sha(layer_raw) != manifest["artifacts"]["layer.json"]:
            raise ValueError("cross-source layer identity drift")
        parent, parent_sha, graph, index, raw, reads = cross.load_structure(Path(manifest["structure_root"]))
        if parent_sha != manifest["structure_manifest_sha256"] or parent["construction_id"] != manifest["construction_id"]:
            raise ValueError("cross-source structure identity mismatch")
        layer = json.loads(layer_raw)
        # Runtime validates the frozen layer as well as its content digest.
        validation = cross.validate(layer, graph, raw, parent["construction_id"])
        result = cls(graph, index, raw, layer, manifest["relation_id"])
        result.initialization.update(**reads, layer_read_operations=2,
            layer_read_bytes=len(manifest_raw) + len(layer_raw), validation=validation,
            loaded_code_identity_read_operations=3, loaded_code_identity_read_bytes=code_bytes,
            total_load_wall_seconds=time.perf_counter() - start)
        return result

    def scope(self, query, requested):
        if requested:
            if requested not in self.cases:
                raise ValueError("case scope must be an exact known full case directory")
            return {"mode": "explicit", "cases": [requested]}

        def mentioned(value):
            return re.search(r"(?<![A-Za-z0-9_./-])" + re.escape(value) + r"(?![A-Za-z0-9_./-])", query) is not None

        exact = [c for c in self.cases if mentioned(c) or mentioned(c.removeprefix("tutorials/"))]
        if exact:
            return {"mode": "literal_path_in_query", "cases": exact}
        names = {c.rsplit("/", 1)[-1] for c in self.cases if mentioned(c.rsplit("/", 1)[-1])}
        candidates = [c for c in self.cases if c.rsplit("/", 1)[-1] in names]
        return {"mode": "ambiguous_basename" if len(candidates) > len(names) else "literal_basename" if candidates else "unrestricted",
                "cases": candidates}

    def anchors(self, node):
        """A node's own span and its actual physical/header parents, never guessed siblings."""
        result = []
        for sid in node["source_span_ids"]:
            a = self.index["spans"][sid]
            if a["kind"] == "original_text_lines":
                result.append({"path": a["path"], "start": a["line_start"], "end": a["line_end"]})
        current = node
        visited = set()
        while True:
            m = current["metadata"]
            parent = m.get("parent_node", m.get("section", m.get("parent_section")))
            if parent not in self.nodes or parent in visited:
                break
            visited.add(parent)
            current = self.nodes[parent]
            if current["structure_kind"] == "dictionary":
                result.append({"path": current["source_file"], "start": current["metadata"]["line_start"],
                               "end": current["metadata"]["open_line"]})
            elif current["structure_kind"] == "section":
                sid = current["source_span_ids"][0]
                a = self.index["spans"][sid]
                result.append({"path": a["path"], "start": a["line_start"], "end": a["line_end"]})
        return result

    def merge_evidence(self, anchors, work):
        ranges = defaultdict(list)
        for a in anchors:
            work["evidence_anchor_visits"] += 1
            ranges[a["path"]].append((a["start"], a["end"]))
        result = []
        for path in sorted(ranges):
            merged = []
            for start, end in sorted(set(ranges[path])):
                if merged and start <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            for start, end in merged:
                quote = "".join(self.lines[path][start - 1:end])
                work["evidence_characters_materialized"] += len(quote)
                result.append({"id": short("e", path, start, end, self.index["inventory"][path]["sha256"]),
                    "path": path, "start": start, "end": end,
                    "text": "".join(f"{i}: {line}" for i, line in enumerate(self.lines[path][start - 1:end], start))})
        return result

    def query(self, query, *, case=None, source="all", file=None, dictionary=None,
              cap=6000, seed_limit=32, seen_groups=(), with_relations=True):
        start = time.perf_counter()
        if source not in {"all", "manual", "tutorial"} or not 1 <= seed_limit <= 256 or cap < 1000:
            raise ValueError("invalid source, seed limit or character budget (minimum 1000)")
        if file is not None and file not in self.raw:
            raise ValueError("unknown exact file scope")
        selected_scope = self.scope(query, case)
        query_for_terms = query
        for candidate in selected_scope["cases"]:
            for spelling in (candidate, candidate.removeprefix("tutorials/"), candidate.rsplit("/", 1)[-1]):
                query_for_terms = re.sub(r"(?<![A-Za-z0-9_./-])" + re.escape(spelling) + r"(?![A-Za-z0-9_./-])", " ", query_for_terms)
        primary_terms = {w.casefold() for w in re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[\u4e00-\u9fff]+", query_for_terms)} - STOP
        # Do not let a known compound identifier (blastProbes/fieldMinMax) turn
        # into a broad search for every occurrence of "blast" or "field".
        query_terms = set().union(*( {term} if term in self.postings else tokens(term) for term in primary_terms)) if primary_terms else set()
        work = Counter()

        def allowed(node):
            if source != "all" and node["source_category"] != source:
                return False
            if node["source_category"] == "tutorial":
                if selected_scope["cases"] and node["scope"]["case_directory"] not in selected_scope["cases"]:
                    return False
                path = node["metadata"].get("dictionary_path", "")
                if dictionary and path != dictionary and not path.startswith(dictionary + "/"):
                    return False
            if file and cross.structure.source_category(file) == node["source_category"] and node["source_file"] != file:
                return False
            return True

        scores = defaultdict(float)
        for term in sorted(query_terms):
            ids = self.postings.get(term, ())
            weight = math.log1p(len(self.nodes) / (1 + len(ids)))
            for nid in sorted(ids):
                work["posting_candidates_visited"] += 1
                n = self.nodes[nid]
                if allowed(n):
                    scores[nid] += weight
        for nid in scores:
            work["ranked_nodes"] += 1
            m = self.nodes[nid]["metadata"]
            # Exact literal selector/key hits, not a model-generated query rewrite.
            if m.get("value_text", "").casefold() in query_terms:
                scores[nid] += 4
            if m.get("key", "").casefold() in query_terms:
                scores[nid] += 2
        ranked = sorted(scores, key=lambda n: (-scores[n], n))[:seed_limit]
        candidates, linked_seeds, cluster_scores = {}, set(), {}
        if with_relations and source == "all":
            for nid in ranked:
                for selector in sorted(self.node_clusters.get(nid, ())):
                    work["relation_cluster_visits"] += 1
                    rs = self.clusters[selector]
                    if not any(allowed(self.nodes[r["source"]]) for r in rs):
                        continue
                    model = self.layer["definitions"][rs[0]["target"]]
                    if file and file.startswith("manual/") and self.nodes[model["section_node"]]["source_file"] != file:
                        continue
                    cluster_scores[selector] = max(cluster_scores.get(selector, 0), scores[nid])
                    linked_seeds.add(nid)
            for selector, score in sorted(cluster_scores.items()):
                rs = self.clusters[selector]
                work["relation_records_expanded"] += len(rs)
                model = self.layer["definitions"][rs[0]["target"]]
                n = self.nodes[rs[0]["instance_node"]]
                anchors = [a for r in rs for side in ("manual_evidence", "tutorial_evidence") for a in r[side]]
                gid = short("g", self.identity, selector)
                evidence = self.merge_evidence(anchors, work)
                candidates[gid] = {"group": {"id": gid, "kind": "cross_source", "model": model["name"],
                    "case": n["scope"]["case_directory"], "file": n["source_file"],
                    "dictionary": n["metadata"]["dictionary_path"],
                    "relations": [{"kind": r["relation"], "parameter": r["parameter"]} for r in rs],
                    "checks": {"literal_type": model["name"], "same_physical_instance": True},
                    "enabled_literals": [e["literal"] for e in rs[0]["enabled_observations"]],
                    "status": "dual_source_literal_alignment"}, "anchors": evidence, "score": score,
                    "terms": set().union(*(self.node_terms[r["source"]] for r in rs)), "canonical_relations": [r["id"] for r in rs]}
        for nid in ranked:
            if nid in linked_seeds:
                continue
            n = self.nodes[nid]
            evidence = self.merge_evidence(self.anchors(n), work)
            gid = short("g", self.identity, n["observation_id"])
            candidates[gid] = {"group": {"id": gid, "kind": "structure", "node_kind": n["structure_kind"],
                "file": n["source_file"], "case": n["scope"]["case_directory"],
                "dictionary": n["metadata"].get("dictionary_path"), "status": n["evidence_status"],
                "flags": n["metadata"].get("flags", [])}, "anchors": evidence, "score": scores[nid],
                "terms": self.node_terms[nid], "canonical_relations": []}
        # Candidates are fully expanded before budget packing. No edge has one end cut off.
        work["groups_materialized_before_budget"] = len(candidates)
        seen = set(seen_groups)
        eligible = [gid for gid in candidates if gid not in seen]
        already_seen = len(candidates) - len(eligible)
        picked, covered, branches = [], set(), set()
        deferred = []

        def render(ids, remaining):
            groups, evidence, sources = [], {}, {}
            for gid in ids:
                c = candidates[gid]
                g = dict(c["group"])
                g["evidence"] = [e["id"] for e in c["anchors"]]
                g["file"] = short("s", g["file"])
                sources[g["file"]] = c["group"]["file"]
                for a in c["anchors"]:
                    sid = short("s", a["path"])
                    sources[sid] = a["path"]
                    evidence[a["id"]] = {"source": sid, "start": a["start"], "end": a["end"], "text": a["text"]}
                groups.append(g)
            result = {"schema": SCHEMA, "snapshot": self.identity, "query": query, "scope": selected_scope,
                "filters": {"source": source, "file": file, "dictionary": dictionary},
                "groups": groups, "sources": sources, "evidence": evidence,
                "continuation": {"omitted_groups": remaining, "already_seen_groups": already_seen},
                "limits": "Lexical navigation only. Literal alignment is not execution, satisfied prerequisites, a default or a dependency. Unaligned concepts require source search."}
            work["serialization_calls"] += 1
            serialized = compact(result)
            work["serialized_characters_including_trials"] += len(serialized)
            return result, serialized

        base, serialized = render([], len(eligible))
        if len(serialized) > cap:
            raise ValueError("query/scope metadata exceeds requested budget")
        while eligible:
            work["packing_rank_visits"] += len(eligible)
            gid = min(eligible, key=lambda i: (
                -(len((candidates[i]["terms"] & query_terms) - covered)
                  + (2 if candidates[i]["group"].get("case") not in branches else 0)),
                -candidates[i]["score"], 0 if candidates[i]["group"]["kind"] == "cross_source" else 1, i))
            eligible.remove(gid)
            result, trial = render(picked + [gid], len(eligible) + len(deferred))
            if len(trial) <= cap:
                picked.append(gid)
                covered |= candidates[gid]["terms"] & query_terms
                branches.add(candidates[gid]["group"].get("case"))
            else:
                deferred.append(gid)
        result, serialized = render(picked, len(deferred))
        if len(serialized) > cap:
            raise AssertionError("final serialized budget invariant failed")
        audit = {"identity": self.identity, "query_terms": sorted(query_terms), "seed_ids": ranked, "candidate_group_ids": sorted(candidates),
            "returned_group_ids": picked, "deferred_group_ids": deferred, "seen_group_ids": sorted(seen),
            "returned_canonical_relations": {gid: candidates[gid]["canonical_relations"] for gid in picked},
            "work": dict(work), "returned_characters": len(serialized), "cap": cap,
            "wall_seconds": time.perf_counter() - start, "runtime_file_reads": 0,
            "source_read_accounting": "All corpus/graph reads occurred and are counted at Engine.load initialization.",
            "model_calls": 0, "model_tokens": 0, "with_relations": with_relations}
        return result, audit


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--relations", required=True, type=Path)
    cli.add_argument("--query", required=True)
    cli.add_argument("--case")
    cli.add_argument("--file")
    cli.add_argument("--dictionary")
    cli.add_argument("--source", choices=("all", "manual", "tutorial"), default="all")
    cli.add_argument("--cap", type=int, default=6000)
    cli.add_argument("--seen-group", action="append", default=[])
    cli.add_argument("--without-relations", action="store_true")
    cli.add_argument("--audit-output", required=True, type=Path,
                     help="新审计 JSON 路径；stdout 只含预算内 payload，不混入内部计量")
    args = cli.parse_args()
    if args.audit_output.exists():
        raise FileExistsError("preserve previous query audit")
    engine = Engine.load(args.relations.resolve())
    payload, audit = engine.query(args.query, case=args.case, source=args.source, file=args.file,
        dictionary=args.dictionary, cap=args.cap, seen_groups=args.seen_group, with_relations=not args.without_relations)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_bytes(cross.encoded({"audit": audit, "initialization": engine.initialization}))
    print(compact(payload))
