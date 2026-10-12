"""原生图排名与结构读取分离；无索引、无题库输入、无跨查询计算缓存。"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import time

from candidate_graph_utils import tokens
from index_free_graph_evidence import scopes


DEFAULTS = {"with_cross": True, "with_scope": True, "with_paths": True, "structured_read": True,
            "seed_limit": 32, "native_limit": 64, "depth": 2, "window_radius": 8, "small_file_characters": 3500}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def literals(text):
    return set(value.rstrip(".,;:") for value in re.findall(r"[A-Za-z_][A-Za-z0-9_./<>+-]*", text))


def norm(value):
    return str(value or "").casefold().replace(" ", "")


def literal_present(text, value):
    return re.search(r"(?<![A-Za-z0-9_])"+re.escape(value)+r"(?![A-Za-z0-9_])", str(text), re.I) is not None


class GraphRetriever:
    def __init__(self, graph_path, corpus, options=None, corpus_manifest=None):
        started = time.monotonic()
        self.corpus = Path(corpus).resolve()
        raw = Path(graph_path).read_bytes()
        self.graph_sha256 = sha(raw)
        self.graph = json.loads(raw)
        self.nodes = self.graph["nodes"]
        self.source_hashes = json.loads(Path(corpus_manifest).read_text())["files"] if corpus_manifest else None
        self.options = {**DEFAULTS, **(options or {})}
        if set(self.options) != set(DEFAULTS):
            raise ValueError("unknown retrieval option")
        self.adjacency = defaultdict(list)
        for edge in self.graph["edges"]:
            self.adjacency[edge["source"]].append((edge["target"], edge, "forward"))
            # 定义→实例反向导航也须受相同跨边/作用域开关约束。
            if edge["relation"] in {"DOCUMENTED_BY", "HAS_ENTRY", "HAS_BLOCK", "HAS_FILE", "HAS_SECTION", "INCLUDES", "CONFLICTS_WITH"}:
                self.adjacency[edge["target"]].append((edge["source"], edge, "reverse"))
        self.load_seconds = time.monotonic()-started

    def rank(self, question, plan=None):
        started = time.monotonic()
        plan = plan or {"translation": "", "needs": []}
        query = question + "\n" + plan.get("translation", "") + "\n" + "\n".join(plan.get("needs", []))
        query_terms = set(tokens(query))
        explicit = literals(question)
        components = {part for value in explicit for part in re.split(r"[/]", value) if part}
        section_numbers = set(re.findall(r"(?<![0-9.])\d+(?:\.\d+){1,5}(?![0-9.])", question))
        # 完整字典字段来自公开题面，不从图值、模型记忆或gold补写。
        dictionary_requests = [v for v in explicit if "/" in v and not v.startswith(("tutorials/", "manual/"))]
        case_names = sorted({n.get("scope", {}).get("case_directory") for n in self.nodes.values() if n.get("scope", {}).get("case_directory")})
        selected = scopes(question, case_names) if self.options["with_scope"] else {"status": "scope_disabled", "cases": []}
        cases = selected["cases"]
        manual_only = bool(re.search(r"只查[^：:]*手册", question)) or "手册" in question and "教程" not in question and not cases
        tutorial_only = bool(re.search(r"只查[^：:]*教程", question)) or "教程" in question and "手册" not in question
        requested_files = {path for path in (self.source_hashes or {}) if any(path == v or path.endswith("/"+v) for v in explicit if "/" in v)}
        ranked, scanned, filtered, field_filtered = [], 0, 0, 0
        for identity, node in self.nodes.items():
            path = str(node.get("path") or "")
            category = path.split("/", 1)[0]
            case = node.get("scope", {}).get("case_directory")
            if self.options["with_scope"] and ((cases and case and case not in cases) or
                    (manual_only and category == "tutorials") or (tutorial_only and category == "manual")):
                filtered += 1
                continue
            if not node.get("evidence"):
                continue
            key, dictionary = str(node.get("key") or ""), str(node.get("dictionary") or "")
            if node["kind"] == "configuration" and key.casefold() in {"format", "version", "class", "location", "object"} and dictionary.startswith("FoamFile/"):
                continue
            # 同键不同对象的硬约束可消融；其他字段仍可为模型声明/包含关系提供背景。
            requests_for_key = [v for v in dictionary_requests if norm(v.rsplit("/", 1)[-1]) == norm(key)] if key else []
            if self.options["with_scope"] and node["kind"] == "configuration" and requests_for_key and not any(norm(dictionary) == norm(v) for v in requests_for_key):
                field_filtered += 1
                continue
            searchable = " ".join(str(node.get(k) or "") for k in ("label", "key", "value", "dictionary", "role", "aliases", "search_text"))
            scanned += len(searchable)
            node_terms = set(tokens(searchable))
            overlap = len(query_terms & node_terms)
            full_field = any(norm(dictionary) == norm(v) for v in dictionary_requests) if dictionary else False
            key_match = bool(key and any(norm(key) == norm(v) for v in components))
            filename_match = path in requested_files or any(norm(Path(path).name) == norm(v) for v in explicit)
            section_match = category == "manual" and any(literal_present(node.get("label", ""), v) for v in section_numbers)
            model_identity = node.get("value") if category == "manual" else None
            model_match = bool(model_identity and any(norm(model_identity) == norm(v) for v in components))
            if not (overlap or full_field or key_match or filename_match or model_match or section_match):
                continue
            lexical = min(8.0, overlap/ max(1, len(query_terms)) * 12 + overlap / max(1, len(node_terms))*3)
            score = lexical + 30*full_field + 16*key_match + 24*filename_match + 20*model_match + 28*section_match
            if case and cases and case in cases:
                score += 8
            if category == "manual" and manual_only or category == "tutorials" and tutorial_only:
                score += 6
            if node["kind"] in {"configuration", "document_unit", "domain_definition", "conditional_assertion"}:
                score += 1
            ranked.append({"node_id": identity, "score": score, "seed_score": score, "route": [], "origin": identity, "visited": [identity],
                           "reasons": {"full_dictionary_match": full_field, "literal_key_match": key_match,
                                       "literal_filename_match": filename_match, "literal_manual_identity_match": model_match}})
        ranked.sort(key=lambda r: (-r["score"], r["node_id"]))
        seeds = ranked[:self.options["seed_limit"]]
        best = {r["node_id"]: r for r in ranked}
        expanded, blocked_cross, blocked_scope = 0, 0, 0
        frontier = seeds
        if self.options["with_paths"]:
            for depth in range(self.options["depth"]):
                following = []
                for row in frontier:
                    origin_case = self.nodes[row["origin"]].get("scope", {}).get("case_directory")
                    for target, edge, direction in self.adjacency[row["node_id"]]:
                        if target in row["visited"]:
                            continue
                        source_kind = self.nodes[edge["source"]]["path"].split("/", 1)[0]
                        target_kind = self.nodes[edge["target"]]["path"].split("/", 1)[0]
                        cross = edge.get("cross_source") or {source_kind, target_kind} == {"manual", "tutorials"}
                        if cross and not self.options["with_cross"]:
                            blocked_cross += 1
                            continue
                        target_case = self.nodes[target].get("scope", {}).get("case_directory")
                        if self.options["with_scope"] and target_case and ((cases and target_case not in cases) or
                                (origin_case and target_case != origin_case)):
                            blocked_scope += 1
                            continue
                        if self.options["with_scope"] and ((manual_only and target_kind == "tutorials") or (tutorial_only and target_kind == "manual")):
                            blocked_scope += 1
                            continue
                        expanded += 1
                        score = row["score"]*.85 + (12 if cross else 1)
                        route = row["route"] + [{"edge_id": edge["id"], "direction": direction, "cross_source": bool(cross),
                                                 "relation": edge["relation"], "conditions": edge.get("conditions", []),
                                                 "condition_satisfied": edge.get("condition_satisfied")}]
                        item = {"node_id": target, "score": score, "seed_score": row["seed_score"], "origin": row["origin"], "visited": row["visited"]+[target],
                                "route": route, "reasons": {"graph_route": True}}
                        if target not in best or score > best[target]["score"]:
                            best[target] = item
                            following.append(item)
                following.sort(key=lambda r: (-r["score"], r["node_id"]))
                frontier = following[:self.options["seed_limit"]]
        candidates = sorted((r for r in best.values() if self.nodes[r["node_id"]].get("evidence")), key=lambda r: (-r["score"], r["node_id"]))
        # 源类型轮换是排名的一部分，尚未读取或计算字符预算；避免同文件字段挤掉另一来源。
        native, path_counts = [], defaultdict(int)
        while candidates and len(native) < self.options["native_limit"]:
            choice = min(candidates, key=lambda r: (-(r["score"]/(1+.25*path_counts[self.nodes[r["node_id"]]["path"]])), r["node_id"]))
            candidates.remove(choice)
            node = self.nodes[choice["node_id"]]
            path_counts[node["path"]] += 1
            native.append({**choice, "native_rank": len(native)+1, "native_unit": choice["node_id"],
                           "path": node["path"], "source_kind": "manual" if node["path"].startswith("manual/") else "tutorial",
                           "scope": node.get("scope", {}), "dictionary": node.get("dictionary"),
                           "node_kind": node["kind"], "role": node.get("role"), "anchors": node["evidence"]})
        elapsed = time.monotonic()-started
        return {"schema": "unbudgeted-native-graph-ranking-v1", "items": native, "question": question, "plan": plan,
                "graph_sha256": self.graph_sha256, "options": self.options, "scope": selected,
                "diagnostic": {"graph_scan_seconds_and_ranking": elapsed, "graph_field_characters_scanned": scanned,
                               "scope_filtered_nodes": filtered, "dictionary_filtered_nodes": field_filtered,
                               "seeds": seeds, "expanded_edges": expanded, "blocked_cross_edges": blocked_cross,
                               "blocked_scope_edges": blocked_scope, "external_index_loaded": False,
                               "rank_is_before_character_budget": True, "model_calls": 0}}

    @staticmethod
    def manual_headings(lines):
        headings, fence = [], None
        for number, line in enumerate(lines, 1):
            mark = re.match(r"^\s*(`{3,}|~{3,})", line)
            if mark:
                if fence is None:
                    fence = mark[1][0]
                elif mark[1][0] == fence:
                    fence = None
                continue
            heading = re.match(r"^(#{1,6})\s+", line) if fence is None else None
            if heading:
                headings.append((number, len(heading[1])))
        return headings

    @staticmethod
    def owner_ranges(lines):
        # 查询内原文结构读取：屏蔽注释/引号但保留换行和位置，识别闭合括号作用域。
        text = "\n".join(lines)
        pattern = r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"'
        masked = re.sub(pattern, lambda m: re.sub(r"[^\n]", " ", m[0]), text, flags=re.S)
        stacks, ranges = {"{": [], "(": []}, []
        number = 1
        for character in masked:
            if character == "\n":
                number += 1
            elif character in stacks:
                stacks[character].append(number)
            elif character in {"}", ")"}:
                opening = "{" if character == "}" else "("
                if stacks[opening]:
                    start = stacks[opening].pop()
                    if start < number:
                        heading = start
                        if not lines[start-1].strip().strip("{("):
                            heading = max(1, start-1)
                        ranges.append((heading, number, opening))
        return ranges

    def read_native(self, ranking):
        started = time.monotonic()
        # 所有读取/词元/作用域复用都只存在于此调用，不写索引或跨查询缓存。
        originals, owners, all_headings, result = {}, {}, {}, []
        for item in ranking["items"]:
            node = self.nodes[item["node_id"]]
            path = item["path"]
            if path not in originals:
                file = (self.corpus / path).resolve()
                if not file.is_relative_to(self.corpus):
                    raise ValueError("source outside corpus")
                raw = file.read_bytes()
                if self.source_hashes is not None and self.source_hashes.get(path) != sha(raw):
                    raise ValueError("authoritative corpus manifest drift")
                originals[path] = (sha(raw), raw.decode().splitlines())
                owners[path] = self.owner_ranges(originals[path][1]) if path.startswith("tutorials/") else []
                all_headings[path] = self.manual_headings(originals[path][1]) if path.startswith("manual/") else []
            source_hash, lines = originals[path]
            # 原图的锚点必须归属于节点文件；禁止用另一文件的行号回读。
            if any(a.get("path", path) != path for a in item["anchors"]):
                raise ValueError("multi-file native node requires explicit adapter")
            headings = all_headings[path]
            ranges = []
            for anchor in item["anchors"]:
                if anchor.get("source_sha256") and anchor["source_sha256"] != source_hash:
                    raise ValueError("graph/source drift")
                start, end = anchor["start"], anchor["end"]
                if self.options["structured_read"]:
                    if path.startswith("manual/"):
                        # 同源手册所属节边界是原文结构，不跟随任何跨来源边。
                        heading = next((i for i, level in reversed(headings) if i <= start), None)
                        if heading:
                            level = next(level for i, level in headings if i == heading)
                            last = next((i-1 for i, lev in headings if i > heading and lev <= level), len(lines))
                            start, end = heading, last
                    elif node["kind"] == "file" and sum(len(x)+1 for x in lines) <= self.options["small_file_characters"]:
                        start, end = 1, len(lines)
                    elif node["kind"] in {"configuration", "dictionary"}:
                        containing = [r for r in owners[path] if r[0] <= start <= end <= r[1]]
                        braces = [r for r in containing if r[2] == "{"]
                        if braces:
                            start, end, _ = min(braces, key=lambda r: r[1]-r[0])
                        if node["kind"] == "dictionary" and node.get("line_start") and node.get("line_end"):
                            start, end = min(start, node["line_start"]), max(end, node["line_end"])
                else:
                    start, end = max(1, start-self.options["window_radius"]), min(len(lines), start+self.options["window_radius"])
                if not 1 <= start <= end <= len(lines):
                    raise ValueError("invalid structured source range")
                ranges.append((start, end))
            merged = []
            for start, end in sorted(set(ranges)):
                if merged and (start <= merged[-1][1]+1 or all(not l.strip() for l in lines[merged[-1][1]:start-1])):
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            result.append({**item, "source_sha256": source_hash,
                           "ranges": [{"start": a, "end": b, "lines": lines[a-1:b]} for a,b in merged]})
        return {"schema": "native-ranking-with-authoritative-source-ranges-v1", "items": result,
                "ranking_diagnostic": ranking["diagnostic"], "reading_seconds": time.monotonic()-started,
                "options": self.options, "limits": "source owner reading is independent of cross-edge traversal; no gold or query cache"}
