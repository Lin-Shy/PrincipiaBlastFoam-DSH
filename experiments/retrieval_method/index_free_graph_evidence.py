"""Index-free graph retrieval with constrained paths and atomic source evidence groups."""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import re
import time

from candidate_graph_utils import sha, tokens, wire
from candidate_paths import Paths, SEMANTIC


# Preserve the original evidence-budgeted candidate set by default; the
# rejected post-hoc experiment may explicitly request one compact overflow
# handle, but production navigation keeps that option disabled.  Ranking and
# the persisted graph stay unchanged, and no hidden text becomes answer
# evidence.
NAVIGATION_EXTRA_CANDIDATES = 0
NAVIGATION_CANDIDATE_LIMIT = 6


def retrieval_terms(text):
    """Add separator-insensitive technical forms without fitting a vocabulary."""
    # ``tokens`` already removes these from its ordinary word stream.  Apply
    # the same rule to the compact identifier stream below; otherwise words
    # such as ``the`` and ``for`` become surprisingly strong graph matches.
    stop = {
        "a", "an", "and", "as", "at", "be", "by", "do", "does", "for",
        "from", "how", "in", "is", "it", "of", "on", "or", "please",
        "that", "the", "this", "to", "use", "used", "using", "what",
        "where", "which", "with",
    }
    result = set(tokens(text))
    for value in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", str(text or "")):
        compact = value.replace("_", "").casefold()
        if len(compact) >= 2 and compact not in stop:
            result.add(compact)
        # Small deterministic morphology bridges common wording differences
        # such as checkpoint/checkpointing and boundary/boundaries.  These are
        # computed during the graph scan and are not a fitted vocabulary.
        if compact.endswith("ing") and len(compact) > 6:
            stem = compact[:-3]
            result.add(stem)
            result.add(stem + "e")
        if compact.endswith("ies") and len(compact) > 5:
            result.add(compact[:-3] + "y")
        elif (compact.endswith("s") and not compact.endswith("ss")
              and len(compact) > 4):
            result.add(compact[:-1])
    return result


def contains_cue(text, cue):
    """Match English semantic cues as words, not identifier substrings."""
    folded, cue = str(text or "").casefold(), str(cue or "").casefold()
    if re.fullmatch(r"[a-z0-9_]+", cue):
        return re.search(
            r"(?<![a-z0-9_])" + re.escape(cue) + r"(?![a-z0-9_])",
            folded,
        ) is not None
    return cue in folded


def identifier_occurs(text, identifier):
    """Match a technical literal without treating 0.6 as a hit on 0.62."""
    text, identifier = str(text or ""), str(identifier or "")
    if re.fullmatch(r"\d+(?:\.\d+)+", identifier):
        return re.search(
            r"(?<![0-9.])" + re.escape(identifier) + r"(?![0-9.])",
            text,
        ) is not None
    if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", identifier):
        return contains_cue(text, identifier)
    return identifier in text


def slot_source_preferences(slot):
    """Infer whether a requested evidence slot asks for documentation or an instance."""
    folded = str(slot or "").casefold()
    manual_cues = (
        "manual", "formula", "meaning", "unit", "default", "defaults", "definition",
        "limitation", "condition", "reference", "手册", "公式", "含义", "单位", "默认",
        "定义", "限制", "条件", "原文", "参考",
    )
    instance_cues = (
        "tutorial", "case", "current", "actual", "file", "path", "setting",
        "location", "教程", "算例", "当前", "实际", "取值", "文件", "路径",
        "位置", "设置", "配置",
    )
    explicit_document_cues = (
        "manual", "formula", "meaning", "unit", "definition", "limitation",
        "reference", "手册", "公式", "含义", "单位", "定义", "限制", "原文", "参考",
    )
    manual = any(contains_cue(folded, cue) for cue in manual_cues)
    instance = any(contains_cue(folded, cue) for cue in instance_cues)
    if (manual and instance
            and not any(contains_cue(folded, cue) for cue in explicit_document_cues)):
        manual = False
    return {
        "manual": manual,
        "instance": instance,
    }


def requested_relations(slot):
    """Map natural evidence requests to relation roles already stored in the graph."""
    folded = str(slot or "").casefold()
    result = set()
    if any(contains_cue(folded, cue) for cue in ("default", "默认")):
        result.add("DEFAULT_WHEN")
    if any(contains_cue(folded, cue) for cue in ("condition", "require", "限制", "条件", "必须")):
        result.update({"REQUIRES_WHEN", "CONFLICTS_WITH"})
    # Merely asking about a model does not request a SELECTS_MODEL edge.  The
    # old broad trigger crowded conceptual questions with unrelated selector
    # examples (for example eTabulated while asking about solid transport).
    if any(contains_cue(folded, cue) for cue in (
        "select", "selection", "selector", "选择", "选择器",
    )):
        result.add("SELECTS_MODEL")
    if any(contains_cue(folded, cue) for cue in ("meaning", "role", "含义", "作用", "单位")):
        result.update({"HAS_ROLE", "PARAMETER_OF", "HAS_UNIT"})
    if any(contains_cue(folded, cue) for cue in ("formula", "relation", "公式", "关系式")):
        result.add("PRODUCES_FIELD")
    if any(contains_cue(folded, cue) for cue in ("include", "引用", "包含")):
        result.update({"INCLUDES", "STATIC_REFERS_TO"})
    return result


def scopes(query, cases):
    def literal(name):
        return re.search(r"(?<![A-Za-z_0-9/])" + re.escape(name) + r"(?![A-Za-z_0-9/])", query) is not None
    exact = [case for case in cases if literal(case) or literal(case.removeprefix("tutorials/"))]
    if exact:
        return {"status": "literal_path", "cases": exact}
    # Match natural spellings of camelCase/underscore case names without a
    # learned vocabulary: e.g. "axisymmetric charge" -> axisymmetricCharge.
    compact_query = re.sub(r"[^a-z0-9]+", "", query.casefold())
    natural = []
    for case in cases:
        compact_name = re.sub(r"[^a-z0-9]+", "", case.rsplit("/", 1)[-1].casefold())
        # Short directory components such as Fluid/Solid occur in ordinary
        # prose too often to establish a case identity on their own.
        if len(compact_name) >= 7 and compact_name in compact_query:
            natural.append(case)
    if natural:
        solvers = {case.split("/")[1] for case in cases
                   if len(case.split("/")) > 2
                   and re.sub(r"[^a-z0-9]+", "", case.split("/")[1].casefold()) in compact_query}
        if solvers:
            natural = [case for case in natural if case.split("/")[1] in solvers]
        return {"status": "natural_case_name" if len(natural) == 1 else "ambiguous",
                "cases": natural}
    solvers = {case.split("/")[1] for case in cases if len(case.split("/")) > 2 and literal(case.split("/")[1])}
    candidates = [case for case in cases
                  if literal(case.rsplit("/", 1)[-1])
                  and (len(case.rsplit("/", 1)[-1]) >= 7 or case.split("/")[1] in solvers)]
    if solvers:
        candidates = [case for case in candidates if case.split("/")[1] in solvers]
    status = "ambiguous" if len(candidates) > 1 else "literal_name" if candidates else "unrestricted"
    return {"status": status, "cases": candidates}


def structured_identifiers(query):
    """Return literal technical identifiers, excluding ordinary prose words."""
    values = (value.rstrip(".,;:") for value in
              re.findall(r"[A-Za-z_][A-Za-z_0-9./-]*", query))
    result = {value for value in values if (
        any(character in value for character in "/._-")
        or any(character.isdigit() for character in value)
        or (any(character.islower() for character in value)
            and any(character.isupper() for character in value[1:]))
        or (value.isupper() and 1 < len(value) <= 12)
        or (len(value) == 2 and value[0].isupper() and value[1].islower())
    )}
    result.update(re.findall(
        r"[A-Za-z_][A-Za-z_0-9]*\([A-Za-z_][A-Za-z_0-9]*\)", query
    ))
    result.update(re.findall(r"(?<![0-9.])\d+(?:\.\d+)+(?![0-9.])", query))
    return result


def bridge_identifier(value):
    """Return a precise case-local symbol suitable for alias propagation."""
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
        return None
    folded = value.casefold()
    if folded in {"foamfile", "type", "model", "file", "name", "object", "format", "class"}:
        return None
    if (any(character.isdigit() for character in value)
            or (any(character.isupper() for character in value)
                and any(character.islower() for character in value))):
        return value
    return None


def informative_slot_terms(slot):
    """Drop navigation boilerplate while retaining the requested fact terms."""
    generic = {
        "actual", "case", "current", "dictionary", "file", "general", "identifier",
        "location", "locations", "main", "model", "name", "path", "paths", "section",
        "settings", "source", "syntax", "tutorial", "using", "value", "values",
        "位置", "实际", "字典", "当前", "文件", "来源", "路径", "设置",
    }
    original = retrieval_terms(slot)
    filtered = {term for term in original if term not in generic}
    return filtered or original


def merged_ranges(anchors):
    by_path = defaultdict(list)
    for anchor in anchors:
        by_path[anchor["path"]].append((anchor["start"], anchor["end"]))
    result = []
    for path, ranges in sorted(by_path.items()):
        merged = []
        for start, end in sorted(set(ranges)):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        result.extend({"path": path, "start": start, "end": end} for start, end in merged)
    return result


def evidence_coordinates(anchors):
    """Identify original lines so overlapping graph groups add no fake novelty."""
    return frozenset(
        (anchor["path"], line)
        for anchor in merged_ranges(anchors)
        for line in range(anchor["start"], anchor["end"] + 1)
    )


class Engine:
    def __init__(self, corpus, graph_path):
        begin = time.monotonic()
        corpus = Path(corpus).resolve()
        self.files, self.source_hashes = {}, {}
        for path in sorted(corpus.rglob("*")):
            if not path.is_file():
                continue
            relative, raw = path.relative_to(corpus).as_posix(), path.read_bytes()
            try:
                text = raw.decode()
            except UnicodeDecodeError:
                continue
            if "\x00" in text:
                continue
            self.files[relative] = text.splitlines()
            self.source_hashes[relative] = sha(raw)
        paths = set(self.files)
        self.cases = sorted({p.removesuffix("/system/controlDict") for p in paths if p.endswith("/system/controlDict")})
        self.graph = json.loads(Path(graph_path).read_text())
        self.nodes, self.corpus_id = self.graph["nodes"], self.graph["corpus_id"]
        self.paths, self.adjacency = Paths(self.graph), defaultdict(list)
        # Query-local traversal repeatedly asks for a node's siblings.  Keep a
        # structural child map in memory; this is derived from the persisted
        # graph at load time and is not an external retrieval index.
        self.children = defaultdict(list)
        self.edges = {edge["id"]: edge for edge in self.graph["edges"]}
        for edge in self.graph["edges"]:
            self.adjacency[edge["source"]].append(edge)
        for node in self.nodes.values():
            if node.get("parent") in self.nodes:
                self.children[node["parent"]].append(node)
            if node["path"] not in self.files and node.get("evidence"):
                raise ValueError("graph node evidence source unavailable")
            for anchor in node.get("evidence", []):
                if anchor.get("source_sha256") and anchor["source_sha256"] != self.source_hashes[anchor["path"]]:
                    raise ValueError("graph evidence source drift")
        self.initialization = {"seconds": time.monotonic() - begin, "graph_loaded": True,
            "source_files": len(self.files), "graph_nodes": len(self.nodes),
            "query_mode": "direct_graph_scan_no_external_index", "model_calls": 0}

    @staticmethod
    def searchable(node):
        role_phrases = []
        if (node.get("key") == "internalField"
                and re.search(r"(?:^|/)0(?:\.orig)?/", node.get("path", ""))):
            role_phrases.extend(["initial field", "初始场"])
        return " ".join(str(value) for value in (
            node.get("label", ""), node.get("search_text", ""), node.get("path", ""),
            node.get("key", ""), node.get("value", ""), node.get("dictionary", ""),
            node.get("role", ""), node.get("object", ""), node.get("condition", ""),
            node.get("subject", ""), node.get("predicate", ""), node.get("subject_role", ""),
            node.get("aliases", ""), role_phrases) if value)

    def contextual_terms(self, node_id):
        """Return node and ancestor terms already represented by graph structure."""
        terms, aliases, visited = set(), set(), set()
        current = self.nodes[node_id]
        while current["id"] not in visited:
            visited.add(current["id"])
            terms.update(retrieval_terms(self.searchable(current)))
            aliases.update(retrieval_terms(wire(current.get("aliases", ""))))
            parent_id = current.get("parent")
            if parent_id not in self.nodes:
                break
            current = self.nodes[parent_id]
        return terms, aliases

    def graph_hits(self, query, case_scopes=(), limit=64, slots=()):
        """Rank a direct graph scan; no fitted vocabulary, passage index or embeddings."""
        query_set = retrieval_terms(query)
        identifiers = structured_identifiers(query)
        slot_values = [slot for slot in slots if isinstance(slot, str) and slot.strip()]
        slot_sets = [retrieval_terms(slot) for slot in slot_values]
        slot_preferences = [slot_source_preferences(slot) for slot in slot_values]
        slot_relations = [requested_relations(slot) for slot in slot_values]
        manual_identifiers = set().union(*(
            structured_identifiers(slot)
            for slot, preference in zip(slot_values, slot_preferences)
            if preference["manual"]
        )) if slot_values else set()
        ranked = []
        per_slot = [[] for _ in slot_sets]
        global_per_slot = [[] for _ in slot_sets]
        manual_per_slot = [[] for _ in slot_sets]
        instance_per_slot = [[] for _ in slot_sets]
        relation_per_slot = [[] for _ in slot_sets]
        manual_unit_rows = []
        query_case_bridges = defaultdict(dict)
        scanned = 0
        # Natural questions often describe one case through several facts which
        # live on different graph nodes.  Accumulate those facts while doing the
        # same full scan, then use the joint per-case coverage as a soft prior.
        # This is deliberately query-local: no case index or fitted state is
        # persisted or loaded outside the graph.
        case_stats = defaultdict(lambda: {
            "slot_best": [0.0 for _ in slot_sets],
            "alias_slot_best": [0.0 for _ in slot_sets],
            "slot_terms_seen": [set() for _ in slot_sets],
            "alias_slot_terms_seen": [set() for _ in slot_sets],
            "slot_rows": [[] for _ in slot_sets],
            "query_alias_terms": set(),
            "matching_nodes": set(),
            "bridges": {},
        })
        identifier_node_counts = defaultdict(int)
        for node_id, node in self.nodes.items():
            scope = node.get("scope", {}).get("case_directory")
            if case_scopes and scope and scope not in case_scopes:
                continue
            searchable = self.searchable(node)
            scanned += len(searchable)
            node_terms = retrieval_terms(searchable)
            alias_terms = retrieval_terms(wire(node.get("aliases", "")))
            coherence_scopes = []
            if scope and not case_scopes:
                coherence_scopes = [scope]
                coherence_scopes.extend(case for case in self.cases
                                        if case != scope and case.startswith(scope + "/"))
                coherence_scopes = sorted(set(coherence_scopes))
            overlap = len(query_set & node_terms)
            exact_matches = [
                (value, identifier_occurs(node.get("path", ""), value))
                for value in identifiers if identifier_occurs(searchable, value)
            ]
            for value, _path_match in exact_matches:
                identifier_node_counts[value] += 1
            scope_bonus = 3 if case_scopes and scope in case_scopes else 0
            if overlap or exact_matches or scope_bonus:
                # Graph nodes are already bounded semantic/structural units.
                # Reward coverage in both directions so a precise configuration
                # node is not buried by a long manual unit sharing generic terms.
                coverage = (overlap / max(1, len(query_set))
                            + .35 * overlap / max(1, len(node_terms)))
                alias_overlap_count = len(query_set & alias_terms)
                alias_bonus = (.5 * min(3, alias_overlap_count)
                               if alias_overlap_count >= 2
                               else .15 * alias_overlap_count)
                ranked.append([coverage + alias_bonus + scope_bonus,
                               node_id, scope, exact_matches])
            # A document unit is a graph-bounded source section rather than a
            # free passage.  Reserve a few concise manual units that jointly
            # cover the natural-language request so broad case metadata cannot
            # consume the seed beam.  This is computed from the current graph
            # scan and persists no text index or query cache.
            if (node.get("kind") == "document_unit"
                    and str(node.get("path") or "").startswith("manual/")
                    and "document_unit Contents " not in str(node.get("label") or "")
                    and overlap >= 3):
                unit_precision = overlap / max(1, len(node_terms))
                unit_coverage = overlap / max(1, len(query_set))
                manual_unit_rows.append([
                    2.0 * overlap + 5.0 * unit_precision + 10.0 * unit_coverage,
                    node_id,
                    scope,
                    [len(slot_terms & node_terms) / max(1, len(slot_terms))
                     for slot_terms in slot_sets],
                    sum(identifier_occurs(str(node.get("label") or ""), identifier)
                        for identifier in manual_identifiers),
                ])
            alias_query_overlap = query_set & alias_terms
            if scope and len(alias_query_overlap) >= 4:
                # The identity must be asserted by this node itself.  Using
                # every node's file basename here makes a generic boundary
                # alias turn all sibling field files (Xi, Su, T, ...) into
                # false semantic bridges.
                for raw_identity in (node.get("key"), node.get("value"), node.get("object")):
                    identity = bridge_identifier(raw_identity)
                    short_symbol = (
                        len(identity) <= 3 or any(character.isdigit() for character in identity)
                    ) if identity else False
                    if identity and short_symbol:
                        query_case_bridges[scope][identity] = max(
                            query_case_bridges[scope].get(identity, 0),
                            len(alias_query_overlap),
                        )
            for coherence_scope in coherence_scopes:
                stats = case_stats[coherence_scope]
                if alias_query_overlap:
                    stats["query_alias_terms"].update(alias_query_overlap)
                    stats["matching_nodes"].add(node_id)
                    for raw_identity in (node.get("key"), node.get("value"), node.get("object")):
                        identity = bridge_identifier(raw_identity)
                        short_symbol = (len(identity) <= 3 or any(character.isdigit() for character in identity)) if identity else False
                        if identity and short_symbol and len(alias_query_overlap) >= 4:
                            stats["bridges"][identity] = max(
                                stats["bridges"].get(identity, 0), len(alias_query_overlap))
            node_relations = {
                relation for relation in SEMANTIC if relation in searchable
            }
            for index, slot_terms in enumerate(slot_sets):
                slot_overlap = len(slot_terms & node_terms)
                relation_specificity = len(node_terms & (query_set | slot_terms))
                if (slot_relations[index] & node_relations
                        and relation_specificity >= 1):
                    relation_per_slot[index].append([
                        2.0 * relation_specificity,
                        node_id,
                        scope,
                    ])
                if slot_overlap:
                    # The fixed bonus ensures that a concise unresolved slot
                    # is not drowned out by the much longer original question.
                    alias_coverage = len(slot_terms & alias_terms) / max(1, len(slot_terms))
                    slot_score = (1 + slot_overlap / max(1, len(slot_terms))
                                  + 1.5 * alias_coverage + scope_bonus)
                    per_slot[index].append([slot_score, node_id, scope])
                    if not scope:
                        global_per_slot[index].append([slot_score, node_id, scope])
                    if str(node.get("path") or "").startswith("manual/"):
                        manual_per_slot[index].append([slot_score, node_id, scope])
                    if scope:
                        instance_per_slot[index].append([slot_score, node_id, scope])
                    for coherence_scope in coherence_scopes:
                        stats = case_stats[coherence_scope]
                        node_coverage = slot_overlap / max(1, len(slot_terms))
                        stats["slot_best"][index] = max(stats["slot_best"][index], node_coverage)
                        stats["alias_slot_best"][index] = max(
                            stats["alias_slot_best"][index], alias_coverage)
                        stats["slot_terms_seen"][index].update(slot_terms & node_terms)
                        stats["alias_slot_terms_seen"][index].update(slot_terms & alias_terms)
                        stats["slot_rows"][index].append((
                            1 + node_coverage + 1.5 * alias_coverage,
                            node_id,
                        ))
                        stats["matching_nodes"].add(node_id)

        case_hypotheses, case_priors = [], {}
        if slot_sets and not case_scopes:
            for scope, stats in case_stats.items():
                slot_coverage = [len(found) / max(1, len(wanted))
                                 for found, wanted in zip(stats["slot_terms_seen"], slot_sets)]
                alias_slot_coverage = [len(found) / max(1, len(wanted))
                                       for found, wanted in zip(stats["alias_slot_terms_seen"], slot_sets)]
                covered = sum(value > 0 for value in slot_coverage)
                alias_covered = sum(value > 0 for value in alias_slot_coverage)
                case_name_matches = query_set & set(tokens(scope.rsplit("/", 1)[-1]))
                # Distinct-slot coverage matters more than repeating one generic
                # term across many nodes.  Unioning matches across a case is the
                # central coherence signal: no individual node has to restate
                # every requested fact. Verified aliases remain the strongest
                # natural-language-to-configuration bridge.
                score = (sum(slot_coverage)
                         + 1.5 * sum(alias_slot_coverage)
                         + .45 * covered
                         + .55 * alias_covered
                         + .04 * len(stats["query_alias_terms"])
                         + (.8 * len(case_name_matches)
                            if len(case_name_matches) >= 2 else 0))
                if score:
                    case_hypotheses.append({
                        "case_directory": scope,
                        "score": round(score, 6),
                        "covered_slots": covered,
                        "alias_covered_slots": alias_covered,
                        "matching_nodes": len(stats["matching_nodes"]),
                    })
            case_hypotheses.sort(key=lambda row: (-row["score"], row["case_directory"]))
            if case_hypotheses:
                top_score = case_hypotheses[0]["score"]
                for rank, row in enumerate(case_hypotheses[:5]):
                    # Keep this a soft preference: manuals and alternative cases
                    # remain reachable, while a case covering several requested
                    # facts gets coherent seeds across its separate files.
                    case_priors[row["case_directory"]] = (
                        1.75 * row["score"] / max(top_score, 1e-9) * (1 - .12 * rank))
        for row in ranked:
            # A literal identifier that occurs on thousands of graph nodes
            # (for example a solver name in every path) must not swamp a rare
            # configuration key. Occurrence counts are computed in this query's
            # full scan and are never persisted as an index.
            row[0] += sum((4 if path_match else 2)
                          / math.sqrt(identifier_node_counts[value])
                          for value, path_match in row[3])
            row[0] += case_priors.get(row[2], 0)
        for rows in per_slot:
            for row in rows:
                row[0] += case_priors.get(row[2], 0)
        ranked.sort(key=lambda row: (-row[0], row[1]))
        chosen = {}
        # Reserve a small, bounded seed quota inside each leading case
        # hypothesis.  The first two hypotheses get enough alternatives to
        # survive generic metadata keys; the remaining three retain one seed
        # per slot so a near-tied correct case is not erased by global ranking.
        for case_rank, hypothesis in enumerate(case_hypotheses[:5]):
            scope = hypothesis["case_directory"]
            depth = 3 if case_rank < 2 else 1
            for rows in case_stats[scope]["slot_rows"]:
                rows.sort(key=lambda row: (-row[0], row[1]))
                for score, node_id in rows[:depth]:
                    adjusted = score + case_priors.get(scope, 0)
                    chosen[node_id] = max(chosen.get(node_id, 0), adjusted)
        # A verified alias on one node can reveal a precise case-local symbol
        # (Su, O2, eTabulated, protectedPatches). Follow that identity only
        # within the same case and graph fields; this avoids the global same-name
        # expansion rejected by candidates 003/004.
        bridge_seed_count = 0
        for hypothesis in case_hypotheses[:2]:
            scope = hypothesis["case_directory"]
            bridges = sorted(case_stats[scope]["bridges"].items(),
                             key=lambda row: (-row[1], row[0]))[:12]
            for identity, alias_strength in bridges:
                identity_folded = identity.casefold()
                matches = []
                for node_id, node in self.nodes.items():
                    if node.get("scope", {}).get("case_directory") != scope:
                        continue
                    identities = {
                        str(node.get("key") or "").casefold(),
                        str(node.get("value") or "").casefold(),
                        str(node.get("object") or "").casefold(),
                        Path(node.get("path", "")).name.casefold(),
                    }
                    if identity_folded not in identities:
                        continue
                    node_terms = retrieval_terms(self.searchable(node))
                    slot_gains = [len(node_terms & terms) / max(1, len(terms))
                                  for terms in slot_sets]
                    matches.append((slot_gains, node_id))
                selected_matches = {}
                for index in range(len(slot_sets)):
                    ranked_matches = sorted(matches, key=lambda row: (-row[0][index], row[1]))
                    if ranked_matches and ranked_matches[0][0][index] > 0:
                        gains, node_id = ranked_matches[0]
                        selected_matches[node_id] = max(selected_matches.get(node_id, 0), gains[index])
                for node_id, slot_gain in selected_matches.items():
                    adjusted = (2 + .2 * min(alias_strength, 3) + slot_gain
                                + case_priors.get(scope, 0))
                    if node_id not in chosen:
                        bridge_seed_count += 1
                    chosen[node_id] = max(chosen.get(node_id, 0), adjusted)
        reserved_case_slot_seeds = len(chosen)
        exact_identifier_seeds = 0
        exact_identifier_parent_seeds = 0
        exact_identifier_parent_ids = set()
        # Preserve rare literal technical identifiers before the much larger
        # case/slot reservations are truncated.  This is especially important
        # for a uniquely named manual model such as ePower: generic instance
        # fields must not consume the whole seed beam first.
        for identifier in sorted(identifiers):
            rows = [row for row in ranked if any(value == identifier for value, _ in row[3])]
            explicit_section = bool(re.fullmatch(r"\d+(?:\.\d+)+", identifier))
            def exact_order(row):
                exact_node = self.nodes[row[1]]
                label = str(exact_node.get("label") or "")
                section_root = (explicit_section and identifier in label
                                and re.search(re.escape(identifier) + r"\.\d", label) is None)
                document_anchor = (exact_node.get("kind") in {"section", "document_unit"}
                                   and identifier.casefold() in label.casefold())
                return (-int(section_root), -int(document_anchor), -row[0], row[1])
            rows.sort(key=exact_order)
            for score, node_id, _scope, _matches in rows[:2]:
                floor = (7.75 if explicit_section else
                         6.0 + 1 / math.sqrt(max(1, identifier_node_counts[identifier])))
                adjusted = max(min(score, 8.0), floor)
                if node_id not in chosen:
                    exact_identifier_seeds += 1
                chosen[node_id] = max(chosen.get(node_id, 0), adjusted)
            # A literal value such as ``p.csv`` is often stored on a child
            # configuration node while the useful bounded evidence unit is
            # its owning dictionary (for example ``pCoeffs``).  Reserve that
            # immediate graph parent so an entire-file configuration context
            # is not the only route to the requested instance evidence.
            parent_rows = []
            for score, node_id, _scope, _matches in rows:
                exact_node = self.nodes[node_id]
                parent_id = exact_node.get("parent")
                parent = self.nodes.get(parent_id)
                if (exact_node.get("kind") in {"configuration", "directive"}
                        and str(exact_node.get("key") or "").casefold() == "file"
                        and identifier_occurs(exact_node.get("value", ""), identifier)
                        and parent
                        and parent.get("kind") == "dictionary"
                        and parent.get("path") == exact_node.get("path")):
                    parent_rows.append((score, parent_id))
            for score, parent_id in sorted(
                    parent_rows, key=lambda row: (-row[0], row[1]))[:2]:
                adjusted = max(min(score, 9.5), 9.0)
                if parent_id not in chosen:
                    exact_identifier_parent_seeds += 1
                chosen[parent_id] = max(chosen.get(parent_id, 0), adjusted)
                exact_identifier_parent_ids.add(parent_id)
        source_role_seeds = 0
        preferred_manual_paths = set()
        for index, preference in enumerate(slot_preferences):
            preferred = []
            if preference["manual"]:
                preferred.extend(manual_per_slot[index])
            if preference["instance"]:
                preferred.extend(instance_per_slot[index])
            preferred.sort(key=lambda row: (-row[0], row[1]))
            for score, node_id, _scope in preferred[:2]:
                adjusted = max(min(score, 7.0), 5.5)
                if node_id not in chosen:
                    source_role_seeds += 1
                chosen[node_id] = max(chosen.get(node_id, 0), adjusted)
                node_path = str(self.nodes[node_id].get("path") or "")
                if preference["manual"] and node_path.startswith("manual/"):
                    preferred_manual_paths.add(node_path)
        relation_role_seeds = 0
        for rows in relation_per_slot:
            rows.sort(key=lambda row: (-row[0], row[1]))
            for score, node_id, _scope in rows[:2]:
                adjusted = max(min(score, 7.0), 6.5)
                if node_id not in chosen:
                    relation_role_seeds += 1
                chosen[node_id] = max(chosen.get(node_id, 0), adjusted)
        manual_unit_seeds = 0
        # A model/section name in the document-unit label is stronger than the
        # same token appearing incidentally inside a broad code example.  This
        # keeps requests such as ePower, HLLC and tabulatedMG attached to their
        # owning manual sections without building a heading or passage index.
        manual_unit_rows.sort(key=lambda row: (-row[4], -row[0], row[1]))
        reserved_manual_rows = manual_unit_rows[:1] if any(
            preference["manual"] for preference in slot_preferences
        ) else []
        # For multi-part requests, one additional unit from the same manual
        # file may close a genuinely different slot (for example an overview
        # configuration block plus a boundary-condition table).  Require a
        # material slot-coverage gain so this does not become broad chapter
        # expansion.
        if reserved_manual_rows and len(slot_sets) >= 3:
            primary = reserved_manual_rows[0]
            primary_path = self.nodes[primary[1]].get("path")
            complements = []
            for row in manual_unit_rows[1:]:
                if self.nodes[row[1]].get("path") != primary_path:
                    continue
                gain = max((value - primary[3][index]
                            for index, value in enumerate(row[3])), default=0.0)
                if gain >= 0.15:
                    complements.append((gain, row))
            if complements:
                complements.sort(key=lambda value: (-value[0], -value[1][0], value[1][1]))
                reserved_manual_rows.append(complements[0][1])
        reserved_manual_unit_ids = [row[1] for row in reserved_manual_rows]
        reserved_manual_unit_priorities = {
            row[1]: 1.0 if index == 0 else 0.5
            for index, row in enumerate(reserved_manual_rows)
        }
        for score, node_id, _scope, _slot_coverages, _label_matches in reserved_manual_rows:
            adjusted = max(min(score, 8.5), 7.25)
            if node_id not in chosen:
                manual_unit_seeds += 1
            chosen[node_id] = max(chosen.get(node_id, 0), adjusted)
        manual_relation_closure_seeds = 0
        for rows in relation_per_slot:
            coherent = [row for row in rows
                        if self.nodes[row[1]].get("path") in preferred_manual_paths]
            coherent.sort(key=lambda row: (-row[0], row[1]))
            for score, node_id, _scope in coherent[:2]:
                adjusted = max(min(score, 7.5), 7.0)
                if node_id not in chosen:
                    manual_relation_closure_seeds += 1
                chosen[node_id] = max(chosen.get(node_id, 0), adjusted)
        reserved_global_slot_seeds = 0
        for rows in global_per_slot:
            rows.sort(key=lambda row: (-row[0], row[1]))
            for score, node_id, _scope in rows[:2]:
                if node_id not in chosen:
                    reserved_global_slot_seeds += 1
                chosen[node_id] = max(chosen.get(node_id, 0), score)
        for rows in per_slot:
            rows.sort(key=lambda row: (-row[0], row[1]))
            for score, node_id, _scope in rows[:3]:
                chosen[node_id] = max(chosen.get(node_id, 0), score)
        for score, node_id, _scope, _exact_matches in ranked:
            chosen[node_id] = max(chosen.get(node_id, 0), score)
            if len(chosen) >= limit:
                break
        ranked_chosen = sorted(chosen.items(), key=lambda row: (-row[1], row[0]))
        path_quota = max(2, limit // 8)
        path_counts = defaultdict(int)
        seeds, seeded = [], set()
        for node_id, score in ranked_chosen:
            node_path = self.nodes[node_id].get("path")
            if path_counts[node_path] >= path_quota:
                continue
            seeds.append((node_id, score)); seeded.add(node_id)
            path_counts[node_path] += 1
            if len(seeds) >= limit:
                break
        if len(seeds) < limit:
            for node_id, score in ranked_chosen:
                if node_id in seeded:
                    continue
                seeds.append((node_id, score))
                if len(seeds) >= limit:
                    break
        return seeds, {"graph_nodes_scanned": len(self.nodes),
            "graph_field_characters_scanned": scanned, "matched_nodes": len(ranked),
            "slot_queries": len(slot_sets),
            "case_hypotheses": case_hypotheses[:5],
            "case_prior_mode": "query_local_full_graph_scan_soft_prior" if case_priors else "disabled",
            "reserved_case_slot_seeds": reserved_case_slot_seeds,
            "reserved_global_slot_seeds": reserved_global_slot_seeds,
            "exact_identifier_seeds": exact_identifier_seeds,
            "exact_identifier_parent_seeds": exact_identifier_parent_seeds,
            "exact_identifier_parent_ids": sorted(exact_identifier_parent_ids),
            "source_role_seeds": source_role_seeds,
            "relation_role_seeds": relation_role_seeds,
            "manual_unit_candidates": len(manual_unit_rows),
            "manual_unit_seeds": manual_unit_seeds,
            "reserved_manual_unit_ids": reserved_manual_unit_ids,
            "reserved_manual_unit_priorities": reserved_manual_unit_priorities,
            "manual_relation_closure_seeds": manual_relation_closure_seeds,
            "seed_path_quota": path_quota,
            "case_local_bridge_seeds": bridge_seed_count,
            "query_case_bridges": {
                scope: [identity for identity, _strength in sorted(
                    identities.items(), key=lambda row: (-row[1], row[0]))[:12]]
                for scope, identities in sorted(query_case_bridges.items())
            },
            "ranking": "query_local_identifier_rarity_plus_source_role_reservation_plus_manual_document_unit_reservation_plus_bidirectional_graph_node_coverage_plus_verified_aliases_plus_scope_plus_unresolved_slot_diversity_plus_query_local_case_coherence; no BM25/vector/inverted index"}

    def evidence(self, anchors):
        result = []
        for anchor in merged_ranges(anchors):
            path, start, end = anchor["path"], anchor["start"], anchor["end"]
            if path not in self.files or not 1 <= start <= end <= len(self.files[path]):
                raise ValueError("candidate evidence out of corpus")
            raw = "\n".join(self.files[path][start - 1:end])
            result.append({**anchor, "id": sha([self.corpus_id, path, start, end])[:24],
                "text": "\n".join(f"{line}: {self.files[path][line - 1]}" for line in range(start, end + 1)),
                "original_range_sha256": sha(raw.encode())})
        return result

    def evidence_char_estimate(self, anchors):
        """Estimate rendered evidence cost without constructing a retrieval index."""
        total = 0
        for anchor in merged_ranges(anchors):
            path, start, end = anchor["path"], anchor["start"], anchor["end"]
            if path not in self.files or not 1 <= start <= end <= len(self.files[path]):
                raise ValueError("candidate evidence out of corpus")
            total += 160 + len(path)
            total += sum(len(self.files[path][line - 1]) + len(str(line)) + 3
                         for line in range(start, end + 1))
        return total

    def evidence_terms(self, anchors):
        """Tokenize the exact candidate lines already anchored by the graph."""
        result = set()
        for anchor in merged_ranges(anchors):
            path, start, end = anchor["path"], anchor["start"], anchor["end"]
            if path not in self.files or not 1 <= start <= end <= len(self.files[path]):
                raise ValueError("candidate evidence out of corpus")
            result.update(retrieval_terms("\n".join(self.files[path][start - 1:end])))
        return result

    def context(self, node_id):
        node, anchors, visited = self.nodes[node_id], list(self.nodes[node_id]["evidence"]), set()
        current = node
        while current.get("parent") in self.nodes and current["parent"] not in visited:
            parent = self.nodes[current["parent"]]
            visited.add(parent["id"])
            anchors.extend(parent["evidence"])
            for sibling in self.children[parent["id"]]:
                key = sibling.get("key") or ""
                if sibling.get("parent") == parent["id"] and (key in {"type", "enabled", "active", "activationModel", "equationOfState", "thermodynamics", "transport", "thermoType"} or key.endswith("Model")):
                    anchors.extend(sibling["evidence"])
            current = parent
        return anchors

    def query(self, question, *, gap="", translation="", seen_groups=(), cap=6000, with_scope=True,
              with_cross=True, with_paths=True, with_groups=True, with_gap=True, slots=(),
              response_mode="evidence",
              navigation_extra_candidates=NAVIGATION_EXTRA_CANDIDATES):
        begin = time.monotonic()
        query = "\n".join(value for value in (question, translation, gap) if value)
        if len(query) > 12000 or cap < 1000:
            raise ValueError("invalid query or evidence budget")
        if response_mode not in {"evidence", "navigation"}:
            raise ValueError("invalid response mode")
        if type(navigation_extra_candidates) is not int or navigation_extra_candidates not in {0, 1}:
            raise ValueError("navigation_extra_candidates must be zero or one")
        navigation_budget_basis = (
            "evidence_budget_plus_one_compact_overflow"
            if navigation_extra_candidates else "evidence_budget_only"
        )
        selected = scopes(query, self.cases) if with_scope else {"status": "scope_constraint_disabled", "cases": []}
        seeds, recall = self.graph_hits(query, case_scopes=selected["cases"],
                                        slots=slots if with_gap else ())
        found, path_audit = self.paths.search(seeds, case_scopes=selected["cases"], with_paths=with_paths,
                                             with_cross=with_cross, with_scope=with_scope)
        query_terms, candidates = retrieval_terms(query), []
        query_identifiers = structured_identifiers(query)
        query_sections = {
            value for value in query_identifiers
            if re.fullmatch(r"\d+(?:\.\d+)+", value)
        }
        instance_detail_identifiers = {
            value for value in query_identifiers
            if not any(value in scope for scope in selected["cases"])
        }
        precise_path_closure = defaultdict(list)
        for identifier in instance_detail_identifiers:
            by_path = defaultdict(list)
            for candidate_id, candidate_node in self.nodes.items():
                candidate_path = candidate_node.get("path")
                precise_identity = " ".join(str(value or "") for value in (
                    candidate_node.get("value"),
                    candidate_node.get("object"),
                    Path(str(candidate_path or "")).name,
                ))
                if candidate_path and identifier_occurs(
                        precise_identity, identifier):
                    by_path[candidate_path].append(candidate_id)
            for candidate_path, candidate_ids in by_path.items():
                if len(candidate_ids) <= 2:
                    precise_path_closure[candidate_path].extend(candidate_ids)
        manual_units = defaultdict(list)
        for candidate_node in self.nodes.values():
            if (candidate_node.get("kind") == "document_unit"
                    and str(candidate_node.get("path") or "").startswith("manual/")):
                manual_units[candidate_node["path"]].append(candidate_node)
        slot_values = [slot for slot in slots if isinstance(slot, str) and slot.strip()]
        slot_terms = [informative_slot_terms(slot) for slot in slot_values]
        slot_identifier_sets = [structured_identifiers(slot) for slot in slot_values]
        slot_identifiers = set().union(*slot_identifier_sets) if slot_values else set()
        slot_preferences = [slot_source_preferences(slot) for slot in slot_values]
        slot_relations = [requested_relations(slot) for slot in slot_values]
        literal_query_nodes_by_path = defaultdict(list)
        for candidate_id, candidate_node in self.nodes.items():
            candidate_key = str(candidate_node.get("key") or "").strip()
            if (len(candidate_key) >= 2
                    and candidate_key.casefold() not in {
                        "foamfile", "class", "format", "object", "version", "location", "type"
                    }
                    and re.search(
                        r"(?<![A-Za-z_0-9])" + re.escape(candidate_key)
                        + r"(?![A-Za-z_0-9])",
                        query,
                        flags=re.IGNORECASE,
                    )):
                literal_query_nodes_by_path[candidate_node.get("path")].append(candidate_id)
        low_information_keys = {
            "foamfile", "class", "default", "format", "object", "version", "location",
        }
        hypothesis_scopes = {row["case_directory"]: rank
                             for rank, row in enumerate(recall.get("case_hypotheses", []))}
        query_case_bridges = {
            scope: {identity.casefold() for identity in identities}
            for scope, identities in recall.get("query_case_bridges", {}).items()
        }
        literal_identity_terms = {
            identifier.casefold() for identifier in query_identifiers
        }
        reserved_manual_unit_ids = set(recall.get("reserved_manual_unit_ids", []))
        reserved_manual_unit_priorities = recall.get(
            "reserved_manual_unit_priorities", {}
        )
        exact_identifier_parent_ids = set(
            recall.get("exact_identifier_parent_ids", [])
        )
        strong_bridge_scopes = set(query_case_bridges)
        for path in found:
            node_id, node = path["node"], self.nodes[path["node"]]
            edges = [self.edges[item["id"]] for item in path["edges"]]
            cross_edges = [edge for edge in edges if edge.get("instance_evidence") and edge.get("definition_evidence")]
            if cross_edges:
                anchors, conditions = [], []
                for edge in cross_edges:
                    anchors.extend(self.context(edge["source"]))
                    anchors.extend(edge["definition_evidence"])
                    for relation in self.adjacency[edge["target"]]:
                        if relation["relation"] in SEMANTIC:
                            anchors.extend(relation["evidence"])
                            conditions.extend(relation.get("conditions", []))
                kind = "cross_source_group"
            else:
                anchors = (
                    self.context(node_id)
                    if with_paths and (
                        node["kind"] == "configuration"
                        or (node["kind"] == "dictionary"
                            and "boundaryField" in str(node.get("dictionary") or ""))
                    )
                    else list(node["evidence"])
                )
                conditions, kind = [], "scoped_source_group"
            for edge in edges:
                anchors.extend(edge.get("evidence", []))
            if (str(node.get("path") or "").startswith("manual/")
                    and node.get("kind") in {"domain_definition", "conditional_assertion"}):
                for anchor in list(anchors):
                    containing = [
                        unit for unit in manual_units.get(anchor["path"], [])
                        if any(unit_anchor["start"] <= anchor["start"]
                               and anchor["end"] <= unit_anchor["end"]
                               for unit_anchor in unit.get("evidence", []))
                    ]
                    if containing:
                        smallest = min(
                            containing,
                            key=lambda unit: min(a["end"] - a["start"]
                                                 for a in unit["evidence"]),
                        )
                        unit_evidence = smallest.get("evidence", [])
                        anchors.extend(unit_evidence)
                        # Document units intentionally exclude Markdown
                        # headings.  Preserve the nearest owning heading so a
                        # formula remains attributable to its named model.
                        if unit_evidence:
                            unit_path = unit_evidence[0]["path"]
                            unit_start = min(value["start"] for value in unit_evidence)
                            for heading_line in range(unit_start - 1, max(0, unit_start - 6), -1):
                                if self.files[unit_path][heading_line - 1].lstrip().startswith("#"):
                                    anchors.append({"path": unit_path, "start": heading_line,
                                                    "end": heading_line})
                                    break
            if (str(node.get("path") or "").startswith("manual/")
                    and node.get("kind") == "section"):
                heading = str(node.get("label") or "").rsplit(" / ", 1)[-1]
                heading = re.sub(r"\s*\[literal-heading\]\s*$", "", heading)
                matching_units = [
                    unit for unit in manual_units.get(node.get("path"), [])
                    if heading and heading in str(unit.get("label") or "")
                ]
                if matching_units:
                    anchors.extend(min(
                        matching_units,
                        key=lambda unit: min(a["end"] - a["start"]
                                             for a in unit["evidence"]),
                    ).get("evidence", []))
            if (str(node.get("path") or "").startswith("manual/")
                    and node.get("kind") == "document_unit"):
                # Document-unit spans intentionally start below their heading.
                # Return the nearest owning heading as provenance when the unit
                # itself is selected, so exact model names such as ``ePower``
                # are not lost even though the formula body was retrieved.
                for anchor in list(anchors):
                    for heading_line in range(
                            anchor["start"] - 1,
                            max(0, anchor["start"] - 6),
                            -1):
                        if self.files[anchor["path"]][heading_line - 1].lstrip().startswith("#"):
                            anchors.append({"path": anchor["path"], "start": heading_line,
                                            "end": heading_line})
                            break
            if node.get("kind") in {"configuration", "dictionary", "directive"}:
                precise_closure_ids = set(precise_path_closure.get(node.get("path"), []))
                literal_closure_ids = set(literal_query_nodes_by_path.get(
                    node.get("path"), []
                ))
                if node.get("kind") == "dictionary":
                    # A dictionary is already a bounded graph unit.  Keep
                    # query-literal closure inside its own source span rather
                    # than pulling every same-file key into the group; sibling
                    # dictionaries remain independently selectable.
                    owner_ranges = node.get("evidence", [])

                    def inside_owner(candidate_id):
                        return any(
                            owner["path"] == anchor["path"]
                            and owner["start"] <= anchor["start"]
                            and anchor["end"] <= owner["end"]
                            for owner in owner_ranges
                            for anchor in self.nodes[candidate_id].get("evidence", [])
                        )

                    precise_closure_ids = {
                        candidate_id for candidate_id in precise_closure_ids
                        if inside_owner(candidate_id)
                    }
                    literal_closure_ids = {
                        candidate_id for candidate_id in literal_closure_ids
                        if inside_owner(candidate_id)
                    }
                for closure_id in sorted(precise_closure_ids):
                    anchors.extend(self.nodes[closure_id].get("evidence", []))
                # If the query names multiple keys in one physical file (for
                # example transport plus #include, or walls plus defaultFaces),
                # keep their source blocks together.  This map is rebuilt by
                # the current full scan; it is not a persisted key index.
                for closure_id in sorted(literal_closure_ids):
                    anchors.extend(self.nodes[closure_id].get("evidence", []))
            if anchors:
                searchable_terms, alias_terms = self.contextual_terms(node_id)
                searchable_terms |= self.evidence_terms(anchors)
                slot_scores = {}
                for index, terms in enumerate(slot_terms):
                    if not terms:
                        continue
                    direct = len(searchable_terms & terms) / len(terms)
                    alias = len(alias_terms & terms) / len(terms)
                    score = min(1.0, direct + 1.5 * alias)
                    if score:
                        slot_scores[index] = score
                candidate_relations = ({relation for relation in SEMANTIC
                                        if relation in str(node.get("label") or "")}
                                       | {edge["relation"] for edge in edges})
                query_relation_overlap = len(searchable_terms & query_terms)
                if query_relation_overlap:
                    for index, _slot in enumerate(slot_values):
                        if slot_relations[index] & candidate_relations:
                            slot_scores[index] = max(slot_scores.get(index, 0.0), 0.75)
                key = str(node.get("key") or "").casefold()
                key_query_alignment = len(
                    retrieval_terms(" ".join(str(value or "") for value in (
                        node.get("key"), node.get("dictionary"), node.get("role")
                    ))) & (query_terms | set().union(*slot_terms) if slot_terms else query_terms)
                )
                slot_identifier_alignment = sum(
                    1 for identifiers_for_slot in slot_identifier_sets
                    if any(retrieval_terms(identifier) & searchable_terms
                           for identifier in identifiers_for_slot)
                )
                low_information = key in low_information_keys
                structured = node.get("kind") in {"configuration", "dictionary", "directive"}
                query_coverage = len(searchable_terms & query_terms) / max(1, len(query_terms))
                node_scope = node.get("scope", {}).get("case_directory")
                origin_scope = self.nodes[path["nodes"][0]].get("scope", {}).get("case_directory")
                candidate_identities = {
                    str(node.get("key") or "").casefold(),
                    str(node.get("value") or "").casefold(),
                    str(node.get("object") or "").casefold(),
                    Path(str(node.get("path") or "")).name.casefold(),
                }
                identity_alignment = bool(
                    candidate_identities
                    & (query_case_bridges.get(node_scope or origin_scope, set())
                       | literal_identity_terms)
                )
                case_bridge_mismatch = bool(
                    strong_bridge_scopes
                    and (node_scope or origin_scope)
                    and (node_scope or origin_scope) not in strong_bridge_scopes
                )
                node_label = str(node.get("label") or "")
                numeric_section_alignment = any(
                    section in node_label
                    and re.search(re.escape(section) + r"\.\d", node_label) is None
                    and node.get("kind") in {"section", "document_unit"}
                    for section in query_sections
                )
                named_section_alignment = (
                    node.get("kind") in {"section", "document_unit"}
                    and any(
                        len(identifier) >= 4
                        and identifier in slot_identifiers
                        and not re.fullmatch(r"\d+(?:\.\d+)+", identifier)
                        and identifier.casefold() in node_label.casefold()
                        for identifier in query_identifiers
                    )
                )
                section_anchor_alignment = (
                    numeric_section_alignment or named_section_alignment
                )
                case_coherence = 0.0
                for candidate_scope in (node_scope, origin_scope):
                    if candidate_scope in hypothesis_scopes:
                        case_coherence = max(
                            case_coherence,
                            max(0.0, 1 - .2 * hypothesis_scopes[candidate_scope]))
                candidates.append({"id": "group:" + sha([path["nodes"], path["edges"]])[:24], "kind": kind,
                    "score": path["score"], "anchors": anchors, "terms": retrieval_terms(node.get("label", "")),
                    "evidence_coordinates": evidence_coordinates(anchors),
                    "node_id": node_id, "path_nodes": path["nodes"],
                    "path": node.get("path"), "key": node.get("key"),
                    "origin_scope": origin_scope,
                    "relations": {edge["relation"] for edge in edges},
                    "include_neighbor_paths": {
                        self.nodes[edge["target"]].get("path")
                        for edge in self.adjacency[node_id]
                        if edge["relation"] == "INCLUDES"
                    },
                    "slot_scores": slot_scores,
                    "manual_slot_alignment": max(
                        (score for index, score in slot_scores.items()
                         if slot_preferences[index]["manual"]
                         and str(node.get("path") or "").startswith("manual/")),
                        default=0.0,
                    ),
                    "manual_source_mismatch": max(
                        (score for index, score in slot_scores.items()
                         if slot_preferences[index]["manual"]
                         and not str(node.get("path") or "").startswith("manual/")
                         and not any(
                             slot_preferences[other_index]["instance"]
                             and other_score > 0
                             for other_index, other_score in slot_scores.items()
                         )),
                        default=0.0,
                    ),
                    "manual_unit_alignment": node_id in reserved_manual_unit_ids,
                    "manual_unit_priority": reserved_manual_unit_priorities.get(
                        node_id, 0.0
                    ),
                    "exact_identifier_parent_alignment": (
                        node_id in exact_identifier_parent_ids
                    ),
                    "slot_identifier_alignment": slot_identifier_alignment,
                    "instance_slot_alignment": max(
                        (score for index, score in slot_scores.items()
                         if slot_preferences[index]["instance"] and node_scope),
                        default=0.0,
                    ),
                    "structured_instance_alignment": (
                        max((score for index, score in slot_scores.items()
                             if slot_preferences[index]["instance"]), default=0.0)
                        if structured else 0.0
                    ),
                    "relation_slot_alignment": max(
                        (score for index, score in slot_scores.items()
                         if slot_relations[index]
                         & candidate_relations),
                        default=0.0,
                    ),
                    "section_anchor_alignment": section_anchor_alignment,
                    "estimated_chars": self.evidence_char_estimate(anchors),
                    "structured": structured, "low_information": low_information,
                    "key_query_alignment": key_query_alignment,
                    "query_coverage": query_coverage,
                    "case_coherence": case_coherence,
                    "identity_alignment": identity_alignment,
                    "case_bridge_mismatch": case_bridge_mismatch,
                    "scope_match": bool(selected["cases"] and node.get("scope", {}).get("case_directory") in selected["cases"]),
                    "metadata": {"scope": node.get("scope"), "dictionary": node.get("dictionary"),
                        "role": node.get("role"), "conditions": conditions, "condition_satisfied": None,
                        "path_relations": [{"relation": edge["relation"], "status": edge["status"],
                            "source": edge["source"], "target": edge["target"],
                            "traversal": path["edges"][index]["direction"]} for index, edge in enumerate(edges)]}})
        if not with_groups:
            flat = {}
            for candidate in candidates:
                for anchor in candidate["anchors"]:
                    identity = sha([anchor["path"], anchor["start"], anchor["end"]])[:24]
                    flat.setdefault(identity, {"id": "ungrouped:" + identity, "kind": "independent_span",
                        "score": candidate["score"], "anchors": [anchor], "terms": set(),
                        "slot_scores": candidate["slot_scores"],
                        "manual_slot_alignment": candidate["manual_slot_alignment"],
                        "manual_source_mismatch": candidate["manual_source_mismatch"],
                        "manual_unit_alignment": candidate["manual_unit_alignment"],
                        "manual_unit_priority": candidate["manual_unit_priority"],
                        "exact_identifier_parent_alignment": candidate[
                            "exact_identifier_parent_alignment"
                        ],
                        "slot_identifier_alignment": candidate["slot_identifier_alignment"],
                        "instance_slot_alignment": candidate["instance_slot_alignment"],
                        "structured_instance_alignment": candidate["structured_instance_alignment"],
                        "relation_slot_alignment": candidate["relation_slot_alignment"],
                        "section_anchor_alignment": candidate["section_anchor_alignment"],
                        "estimated_chars": self.evidence_char_estimate([anchor]),
                        "evidence_coordinates": evidence_coordinates([anchor]),
                        "structured": candidate["structured"],
                        "key_query_alignment": candidate["key_query_alignment"],
                        "low_information": candidate["low_information"],
                        "query_coverage": candidate["query_coverage"],
                        "case_coherence": candidate["case_coherence"],
                        "identity_alignment": candidate["identity_alignment"],
                        "case_bridge_mismatch": candidate["case_bridge_mismatch"],
                        "node_id": candidate["node_id"],
                        "path_nodes": candidate["path_nodes"], "path": anchor["path"],
                        "key": candidate["key"], "origin_scope": candidate["origin_scope"],
                        "relations": set(),
                        "include_neighbor_paths": candidate["include_neighbor_paths"],
                        "scope_match": candidate["scope_match"], "metadata": {}})
            candidates = list(flat.values())
        candidates = [candidate for candidate in candidates if candidate["id"] not in set(seen_groups)]
        chosen_groups, navigation_candidates = [], []
        navigation_overflow = []
        evidence, sources, covered, deferred = {}, {}, set(), []
        covered_slot_scores = [0.0 for _ in slot_terms]
        selection_trace = []
        selected_source_paths = set()
        selected_evidence_coordinates = set()
        leading_case_scopes = set(selected.get("cases", []))
        hypotheses = recall.get("case_hypotheses", [])
        if not leading_case_scopes and hypotheses:
            top_hypothesis_score = hypotheses[0]["score"]
            leading_case_scopes.update(
                row["case_directory"] for row in hypotheses[:2]
                if row["score"] >= 0.9 * top_hypothesis_score
            )
        while candidates:
            slot_leader_pools = []
            slot_leaders = []
            for index, preference in enumerate(slot_preferences):
                pool = candidates
                if preference["manual"]:
                    manual_pool = [
                        candidate for candidate in candidates
                        if str(candidate["path"] or "").startswith("manual/")
                        and candidate["slot_scores"].get(index, 0.0) > 0
                    ]
                    if manual_pool:
                        pool = manual_pool
                elif leading_case_scopes:
                    coherent_pool = [
                        candidate for candidate in candidates
                        if candidate["origin_scope"] in leading_case_scopes
                        and candidate["slot_scores"].get(index, 0.0) > 0
                    ]
                    if coherent_pool:
                        pool = coherent_pool
                slot_leader_pools.append({candidate["id"] for candidate in pool})
                slot_leaders.append(max(
                    (candidate["slot_scores"].get(index, 0.0) for candidate in pool),
                    default=0.0,
                ))
            def priority(item):
                marginal_slots = sum(max(0.0, score ** 2 - covered_slot_scores[index] ** 2)
                                     for index, score in item["slot_scores"].items())
                # Preserve the strongest remaining evidence for each explicit
                # unresolved slot.  Otherwise one compact group matching many
                # configuration words can consume the budget before a longer
                # single-slot definition (for example a named manual model)
                # is returned.
                slot_leader_bonus = 2.5 * sum(
                    1 for index, score in item["slot_scores"].items()
                    if (slot_identifier_sets[index]
                        or slot_relations[index]
                        & {"SELECTS_MODEL", "INCLUDES", "STATIC_REFERS_TO"})
                    and score >= 0.25
                    and item["id"] in slot_leader_pools[index]
                    and score >= slot_leaders[index] - 1e-12
                    and score > covered_slot_scores[index] + 1e-12
                )
                needs_manual_source = (
                    any(preference["manual"] for preference in slot_preferences)
                    and not any(path.startswith("manual/")
                                for path in selected_source_paths)
                )
                manual_diversity = 0.0
                if (needs_manual_source
                        and str(item["path"] or "").startswith("manual/")
                        and item["origin_scope"] is None):
                    manual_diversity = 6.0 * sum(
                        score ** 2 for index, score in item["slot_scores"].items()
                        if slot_preferences[index]["manual"]
                    )
                source_novelty_eligible = (
                    str(item["path"] or "").startswith("manual/")
                    or item["key_query_alignment"] > 0
                )
                source_novelty = (
                    2.0 * max(item["slot_scores"].values(), default=0.0)
                    if (source_novelty_eligible
                        and item["path"] not in selected_source_paths) else 0.0
                )
                redundant_source = (
                    item["path"] in selected_source_paths
                    and marginal_slots < 0.05
                    and not item["exact_identifier_parent_alignment"]
                )
                relevance = (
                    .45 * item["score"]
                    + 2.5 * marginal_slots
                    + slot_leader_bonus
                    + .65 * item["scope_match"]
                    + 1.2 * item["case_coherence"]
                    + 7.0 * item["identity_alignment"]
                    + ((1.5 if item["slot_scores"] else .2)
                       * (item["kind"] == "cross_source_group"))
                    + 1.8 * bool(item["include_neighbor_paths"] & selected_source_paths)
                    + .35 * item["structured"]
                    + 1.5 * item["query_coverage"]
                    + 2.5 * item["manual_slot_alignment"]
                    + 45.0 * item["manual_unit_priority"]
                    + 10.0 * item["exact_identifier_parent_alignment"]
                    + 5.0 * item["slot_identifier_alignment"]
                    + 4.0 * (
                        item["structured"] and item["slot_identifier_alignment"]
                    )
                    + 1.5 * item["instance_slot_alignment"]
                    + 2.0 * item["structured_instance_alignment"]
                    + 3.0 * item["relation_slot_alignment"]
                    + .75 * min(3, item["key_query_alignment"])
                    + 4.0 * item["section_anchor_alignment"]
                    + manual_diversity
                    + source_novelty
                    - 4.0 * item["manual_source_mismatch"]
                    - 5.0 * item["case_bridge_mismatch"]
                    - 15.0 * redundant_source
                    - 1.5 * item["low_information"]
                    + .012 * len((item["terms"] & query_terms) - covered)
                )
                coordinates = item["evidence_coordinates"]
                evidence_novelty = (len(coordinates - selected_evidence_coordinates)
                                    / max(1, len(coordinates)))
                return (relevance * max(0.35, evidence_novelty)
                        / (1 + item["estimated_chars"] / 2800))
            chosen = min(candidates, key=lambda item: (-(
                priority(item)
            ), item["id"]))
            chosen_priority = priority(chosen)
            candidates.remove(chosen)
            compact_ranges = [
                {"path": anchor["path"], "start": anchor["start"],
                 "end": anchor["end"]}
                for anchor in merged_ranges(chosen["anchors"])
            ]
            navigation_candidate = {
                "id": chosen["id"],
                "node": self.navigation_node(chosen["node_id"], with_context=True),
                "relations": [
                    {
                        **relation,
                        "source_label": self._navigation_value(
                            self.nodes[relation["source"]].get("label"), limit=120
                        ),
                        "target_label": self._navigation_value(
                            self.nodes[relation["target"]].get("label"), limit=120
                        ),
                    }
                    for relation in chosen["metadata"].get("path_relations", [])
                ],
                "sources": compact_ranges,
            }
            if response_mode == "navigation":
                # Keep the original admission decision: a group belongs to the
                # base catalogue only when its fully rendered evidence would
                # have fit the shared public budget.  The rendered text below
                # is never returned in navigation mode.
                group_evidence = self.evidence(chosen["anchors"])
                trial_evidence, trial_sources = dict(evidence), dict(sources)
                for anchor in group_evidence:
                    source_id = sha(anchor["path"])[:16]
                    trial_sources[source_id] = anchor["path"]
                    trial_evidence[anchor["id"]] = {
                        "source": source_id, "start": anchor["start"],
                        "end": anchor["end"], "text": anchor["text"],
                    }
                evidence_group = {
                    "id": chosen["id"], "kind": chosen["kind"],
                    "evidence": [anchor["id"] for anchor in group_evidence],
                    **chosen["metadata"],
                }
                evidence_trial = {
                    "status": "ok", "scope": selected,
                    "groups": chosen_groups + [evidence_group],
                    "sources": trial_sources, "evidence": trial_evidence,
                    "citation_rule": (
                        "Use mapped exact numbered source evidence; graph relations "
                        "do not prove execution."
                    ),
                }
                if with_gap:
                    evidence_trial["gaps"] = {
                        "deferred_groups": len(deferred) + len(candidates),
                        "requested_slots": list(slots),
                        "not_proven": (
                            "condition satisfaction, execution, and absence are not "
                            "established by retrieval"
                        ),
                    }
                trial = {
                    "schema": "principia-navigation-v1",
                    "status": "ok",
                    "scope": selected,
                    "candidates": navigation_candidates + [navigation_candidate],
                    "navigation_only": True,
                    "catalogue_policy": {
                        "budget_basis": navigation_budget_basis,
                        "candidate_limit": NAVIGATION_CANDIDATE_LIMIT,
                        "compact_overflow_limit": navigation_extra_candidates,
                    },
                    "source_read_rule": (
                        "Navigation metadata is not answer evidence; read selected "
                        "candidate sources from the original corpus before citing."
                    ),
                }
                if with_gap:
                    trial["gaps"] = {
                        "deferred_groups": len(deferred) + len(candidates),
                        "requested_slots": list(slots),
                        "not_proven": (
                            "condition satisfaction, execution, and absence are not "
                            "established by retrieval"
                        ),
                    }
                accepted = (len(navigation_candidates) < NAVIGATION_CANDIDATE_LIMIT
                            and len(wire(evidence_trial)) <= cap
                            and len(wire(trial)) <= cap)
                group = evidence_group
            else:
                group_evidence = self.evidence(chosen["anchors"])
                trial_evidence, trial_sources = dict(evidence), dict(sources)
                for anchor in group_evidence:
                    source_id = sha(anchor["path"])[:16]
                    trial_sources[source_id] = anchor["path"]
                    trial_evidence[anchor["id"]] = {
                        "source": source_id, "start": anchor["start"],
                        "end": anchor["end"], "text": anchor["text"],
                    }
                group = {"id": chosen["id"], "kind": chosen["kind"],
                         "evidence": [a["id"] for a in group_evidence],
                         **chosen["metadata"]}
                trial = {"status": "ok", "scope": selected,
                    "groups": chosen_groups + [group], "sources": trial_sources,
                    "evidence": trial_evidence,
                    "citation_rule": "Use mapped exact numbered source evidence; graph relations do not prove execution."}
                if with_gap:
                    trial["gaps"] = {"deferred_groups": len(deferred) + len(candidates),
                        "requested_slots": list(slots),
                        "not_proven": "condition satisfaction, execution, and absence are not established by retrieval"}
                accepted = len(wire(trial)) <= cap
            if accepted:
                chosen_groups.append(group)
                if response_mode == "navigation":
                    navigation_candidates.append(navigation_candidate)
                    evidence, sources = trial_evidence, trial_sources
                else:
                    evidence, sources = trial_evidence, trial_sources
                selected_source_paths = set(sources.values())
                if response_mode == "navigation":
                    selected_source_paths = {
                        source["path"]
                        for candidate in navigation_candidates
                        for source in candidate["sources"]
                    }
                selected_evidence_coordinates.update(chosen["evidence_coordinates"])
                covered |= chosen["terms"] & query_terms
                for index, score in chosen["slot_scores"].items():
                    covered_slot_scores[index] = max(covered_slot_scores[index], score)
            else:
                deferred.append(chosen["id"])
                if response_mode == "navigation":
                    navigation_overflow.append({
                        "priority": chosen_priority,
                        "candidate": navigation_candidate,
                    })
            if len(selection_trace) < 20:
                selection_trace.append({
                    "accepted": accepted, "priority": round(chosen_priority, 6),
                    "path": chosen["path"], "key": chosen["key"],
                    "kind": chosen["kind"], "origin_scope": chosen["origin_scope"],
                    "identity_alignment": chosen["identity_alignment"],
                    "manual_unit_alignment": chosen["manual_unit_alignment"],
                    "manual_unit_priority": chosen["manual_unit_priority"],
                    "exact_identifier_parent_alignment": chosen[
                        "exact_identifier_parent_alignment"
                    ],
                    "estimated_chars": chosen["estimated_chars"],
                    "slot_scores": {str(index): round(score, 6)
                                    for index, score in chosen["slot_scores"].items()},
                })
        result = {"status": "ok", "scope": selected, "groups": chosen_groups, "sources": sources,
            "evidence": evidence, "citation_rule": "Use mapped exact numbered source evidence; graph relations do not prove execution."}
        if with_gap:
            result["gaps"] = {"deferred_groups": len(deferred), "requested_slots": list(slots),
                "not_proven": "condition satisfaction, execution, and absence are not established by retrieval"}
        if response_mode == "navigation":
            # Add at most one high-priority rejected handle only after the base
            # catalogue is complete, so it cannot perturb original ranking or
            # marginal-coverage decisions.
            for overflow in sorted(
                    navigation_overflow,
                    key=lambda row: (-row["priority"], row["candidate"]["id"])
            )[:navigation_extra_candidates]:
                if len(navigation_candidates) >= NAVIGATION_CANDIDATE_LIMIT:
                    break
                proposed = navigation_candidates + [overflow["candidate"]]
                compact_trial = {
                    "schema": "principia-navigation-v1", "status": "ok",
                    "scope": selected, "candidates": proposed,
                    "navigation_only": True,
                    "catalogue_policy": {
                        "budget_basis": navigation_budget_basis,
                        "candidate_limit": NAVIGATION_CANDIDATE_LIMIT,
                        "compact_overflow_limit": navigation_extra_candidates,
                    },
                    "source_read_rule": (
                        "Navigation metadata is not answer evidence; read selected "
                        "candidate sources from the original corpus before citing."
                    ),
                }
                if with_gap:
                    compact_trial["gaps"] = {
                        "deferred_groups": max(0, len(deferred) - 1),
                        "requested_slots": list(slots),
                        "not_proven": (
                            "condition satisfaction, execution, and absence are not "
                            "established by retrieval"
                        ),
                    }
                if len(wire(compact_trial)) <= cap:
                    navigation_candidates = proposed
                    deferred.remove(overflow["candidate"]["id"])
            result = {
                "schema": "principia-navigation-v1",
                "status": "ok",
                "scope": selected,
                "candidates": navigation_candidates,
                "navigation_only": True,
                "catalogue_policy": {
                    "budget_basis": navigation_budget_basis,
                    "candidate_limit": NAVIGATION_CANDIDATE_LIMIT,
                    "compact_overflow_limit": navigation_extra_candidates,
                },
                "source_read_rule": (
                    "Navigation metadata is not answer evidence; read selected "
                    "candidate sources from the original corpus before citing."
                ),
            }
            if with_gap:
                result["gaps"] = {
                    "deferred_groups": len(deferred),
                    "requested_slots": list(slots),
                    "not_proven": (
                        "condition satisfaction, execution, and absence are not "
                        "established by retrieval"
                    ),
                }
        if len(wire(result)) > cap:
            raise ValueError("scope/slot metadata exceeds budget")
        return result, {"seconds": time.monotonic() - begin, "recall": {"work": recall}, "paths": path_audit,
            "returned_group_ids": ([candidate["id"] for candidate in navigation_candidates]
                                   if response_mode == "navigation"
                                   else [group["id"] for group in chosen_groups]),
            "deferred_group_ids": deferred,
            "selection": {"mode": "marginal_slot_gain_per_estimated_evidence_character",
                "covered_slot_scores": [round(value, 6) for value in covered_slot_scores],
                "trace": selection_trace},
            "graph_loaded": True, "external_index_loaded": False, "returned_characters": len(wire(result))}

    @staticmethod
    def _navigation_value(value, *, limit=240):
        """Bound graph metadata without copying raw evidence into the catalogue."""
        if value in (None, "", [], {}):
            return None
        if isinstance(value, str):
            return value if len(value) <= limit else value[:limit - 1] + "…"
        if isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, list):
            compact = []
            for item in value[:8]:
                projected = Engine._navigation_value(item, limit=80)
                if projected is not None:
                    compact.append(projected)
            return compact or None
        return None

    def navigation_node(self, node_id, *, with_context=False):
        """Project actual graph nodes into useful, non-evidentiary source cards.

        The former projection spent most of its budget on provenance hashes in
        ``scope`` while suppressing configuration values and relation endpoint
        labels.  That left a source-selecting model with opaque node ids.  This
        projection exposes only bounded fields already persisted on graph
        nodes; exact source text remains unavailable until ``read_sources``.
        """
        node = self.nodes[node_id]
        result = {}
        for key in (
            "id", "kind", "label", "path", "key", "dictionary", "role",
            "name", "subject", "predicate", "object", "condition", "value",
            "status", "effective_state", "selector_keys", "input_signature",
            "output_signature",
        ):
            projected = self._navigation_value(node.get(key))
            if projected is not None:
                result[key] = projected
        scope = node.get("scope") if isinstance(node.get("scope"), dict) else {}
        compact_scope = {
            key: scope[key]
            for key in (
                "case_directory", "case_relative_file", "region_directory_hint",
                "time_directory_hint", "field_file_hint",
                "top_level_tutorial_directory",
            )
            if scope.get(key) not in (None, "", [], {})
        }
        if compact_scope:
            result["scope"] = compact_scope
        if not with_context:
            return result

        def context_node(context_id):
            context = self.nodes[context_id]
            compact = {}
            for key in (
                "kind", "label", "key", "dictionary", "role", "name",
                "subject", "predicate", "object", "condition", "value",
            ):
                projected = self._navigation_value(context.get(key), limit=120)
                if projected is not None:
                    compact[key] = projected
            return compact

        parent_id = node.get("parent")
        if parent_id in self.nodes:
            result["parent"] = context_node(parent_id)
        children = []
        for child in sorted(
                self.children.get(node_id, []),
                key=lambda row: (
                    row.get("line_start") if type(row.get("line_start")) is int else 10**9,
                    row.get("id", ""),
                )):
            projected = context_node(child["id"])
            if projected:
                children.append(projected)
            if len(children) >= 8:
                break
        if children:
            result["children"] = children
        return result
