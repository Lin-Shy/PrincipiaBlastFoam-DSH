"""冻结 Graphify 上的过滤兼容与完整关系返回消融；不改图、不读取原文。"""
from __future__ import annotations

from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import time

try:
    from . import graphify_query_backend as reference
except ImportError:
    import graphify_query_backend as reference


VARIANTS = {
    "original": (False, False),
    "compatible": (True, False),
    "atomic": (False, True),
    "combined": (True, True),
}


def wire(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    account("json_serialization_calls")
    account("json_serialized_characters", len(encoded))
    return encoded


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def account(name, amount=1):
    meter = reference.METER.get()
    if meter is not None:
        meter[name] += amount


def ordered_nodes(graph, nodes, seeds):
    """与固定版本 renderer 的节点顺序一致；不改变入口打分。"""
    seed_hits = [node for node in seeds if node in nodes]
    distance = {node: 0 for node in seed_hits}
    pending = deque(seed_hits)
    while pending:
        node = pending.popleft()
        neighbors = graph.neighbors(node)
        for neighbor in neighbors:
            account("packing_neighbor_checks")
            if neighbor in nodes and neighbor not in distance:
                distance[neighbor] = distance[node] + 1
                pending.append(neighbor)
    account("packing_node_sort_records", len(nodes) - len(seed_hits))
    return seed_hits + sorted(nodes - set(seeds),
        key=lambda n: (distance.get(n, 1 << 30), -graph.degree(n), str(n)))


def resolve_filters(serve, graph, question, compatible):
    requested, origin = serve._resolve_context_filters(question, None)
    available = set()
    if compatible and requested:
        for _, _, data in graph.edges(data=True):
            account("compatibility_edge_records_scanned")
            value = data.get("context")
            if isinstance(value, str):
                available.add(value)
    used = [value for value in requested if value in available] if compatible else requested
    return used, origin, {"requested": requested, "used": used,
        "dropped": [value for value in requested if value not in used],
        "available": sorted(available) if compatible and requested else None}


def traverse(serve, graph, question, compatible):
    """固定版本 _query_graph_text 的协调步骤；过滤是唯一可选差异。"""
    terms = serve._query_terms(question)
    scores = serve._score_query(graph, terms, collect_per_term_seeds=True)
    winners = scores.best_seed_by_term
    intent = {term for term in winners if term in serve._RELATIONAL_INTENT_TERMS}
    if intent and any(term not in serve._RELATIONAL_INTENT_TERMS for term in terms):
        winners = {term: node for term, node in winners.items()
                   if term not in serve._RELATIONAL_INTENT_TERMS}
    seeds = serve._pick_seeds(scores.ranked, G=graph, best_seed_by_term=winners)
    if not seeds:
        return None, [], set(), [], "", {"requested": [], "used": [], "dropped": [], "available": None}
    filters, origin, filter_audit = resolve_filters(serve, graph, question, compatible)
    view = serve._filter_graph_by_context(serve._traversal_view(graph), filters)
    nodes, edges = serve._bfs(view, seeds, 2)
    parts = [f"Graph: graphify-out/graph.json ({graph.number_of_nodes()} nodes)",
        "Traversal: BFS depth=2", f"Start: {[graph.nodes[n].get('label', n) for n in seeds]}"]
    if filters:
        parts.append(f"Context: {', '.join(filters)} ({origin})")
    parts.append(f"{len(nodes)} nodes found")
    return view, seeds, nodes, edges, " | ".join(parts) + "\n\n", filter_audit


def atomic_payload(serve, graph, nodes, edges, seeds, header, native_budget, cap, inverse):
    """沿用原版安全序列化字段，以不可分的端点＋边组填充两个预算。"""
    order = ordered_nodes(graph, nodes, seeds)
    rank = {node: index for index, node in enumerate(order)}
    # 只对同一候选集合执行一次无截断的原版字段序列化。
    complete = serve._subgraph_to_text(graph, nodes, edges, token_budget=10**12, seeds=seeds)
    lines = complete.splitlines()
    if len(lines) != len(nodes) + len(edges):
        raise ValueError("Pinned renderer line structure changed")
    if any(not line.startswith("NODE ") for line in lines[:len(nodes)]):
        raise ValueError("Pinned node rendering changed")
    if any(not line.startswith("EDGE ") for line in lines[len(nodes):]):
        raise ValueError("Pinned edge rendering changed")
    account("packing_complete_render_characters", len(complete))
    account("graph_path_mapping_input_characters", len(complete) + len(header))
    mapped = [reference.original_paths(line, inverse) for line in lines]
    header = reference.original_paths(header, inverse)
    account("graph_path_mapping_output_characters", sum(map(len, mapped)) + len(header))
    node_lines = dict(zip(order, mapped[:len(nodes)]))
    edge_lines = mapped[len(nodes):]
    edge_order = sorted(range(len(edges)), key=lambda i: (
        min(rank[edges[i][0]], rank[edges[i][1]]),
        max(rank[edges[i][0]], rank[edges[i][1]]), i))
    account("packing_edge_sort_records", len(edges))
    incident = {node: [] for node in seeds}
    for index in edge_order:
        for node in set(edges[index]):
            if node in incident:
                incident[node].append(index)
        account("packing_incidence_records")

    selected_nodes, selected_edges, output = set(), set(), []
    notice = "[!] TRUNCATED: candidate nodes/edges omitted by budget; read original sources.\n"
    # 固定通知预留；避免靠动态数字长度或末尾截断破坏已经选定的组。
    def payload(body, truncated):
        return {"status": "ok", "graph_navigation": header + (notice if truncated else "") + body,
                "truncated": truncated, "evidence": "derived_navigation_only_read_original_sources"}

    def attempt(extra_nodes, edge_index=None):
        fresh = sorted(set(extra_nodes) - selected_nodes, key=rank.__getitem__)
        addition = [node_lines[node] for node in fresh]
        if edge_index is not None and edge_index not in selected_edges:
            addition.append(edge_lines[edge_index])
        if not addition:
            return False
        body = "\n".join(output + addition)
        encoded = wire(payload(body, True))
        account("packing_candidate_groups")
        account("packing_serialized_candidate_characters", len(encoded))
        if len(notice) + len(body) > native_budget * 3 or len(encoded) > cap:
            account("packing_rejected_groups")
            return False
        output.extend(addition)
        selected_nodes.update(fresh)
        if edge_index is not None:
            selected_edges.add(edge_index)
        return True

    # 每个种子先有一次带关系的机会，避免首个 hub 占满整个预算。
    for seed in seeds:
        candidates = incident.get(seed, [])
        if not candidates or not attempt(edges[candidates[0]], candidates[0]):
            attempt([seed])
    for index in edge_order:
        if index not in selected_edges:
            attempt(edges[index], index)
    for node in order:
        if node not in selected_nodes:
            attempt([node])
    truncated = len(selected_nodes) < len(nodes) or len(selected_edges) < len(edges)
    body = "\n".join(output)
    result = payload(body, truncated)
    if len(wire(result)) > cap:
        # 即使 header/种子标签本身过大，也不能破坏公共预算或伪造完整结果。
        result = {"status": "item_exceeds_budget", "graph_navigation": "",
                  "truncated": True, "evidence": "derived_navigation_only_read_original_sources"}
        selected_nodes, selected_edges = set(), set()
    edge_records = [{"index": i, "endpoints": list(edges[i]), "line": edge_lines[i]}
                    for i in sorted(selected_edges)]
    for record in edge_records:
        if not set(record["endpoints"]) <= selected_nodes:
            raise AssertionError("Atomic edge missing an endpoint")
    audit = {"shown_nodes": [node for node in order if node in selected_nodes],
        "shown_edges": edge_records, "omitted_nodes": len(nodes)-len(selected_nodes),
        "omitted_edges": len(edges)-len(selected_edges),
        "body_characters": len(body) if selected_nodes else 0,
        "native_body_limit": native_budget * 3, "reserved_notice_characters": len(notice),
        "endpoint_records": {node: node_lines[node] for node in order if node in selected_nodes}}
    return result, audit


class Backend(reference.Backend):
    def __init__(self, path):
        super().__init__(Path(path))
        if self.graph.is_multigraph():
            raise ValueError("This pinned experiment supports the two simple frozen graphs only")

    def payload(self, question, native_budget, cap, inverse, variant):
        if variant not in VARIANTS:
            raise ValueError("Unknown query variant")
        if not isinstance(question, str) or not question.strip() or len(question) > 12000:
            raise ValueError("Invalid query")
        if type(cap) is not int or cap < 1000 or type(native_budget) is not int or native_budget < 100:
            raise ValueError("Invalid budget")
        import graphify.serve as serve
        compatible, atomic = VARIANTS[variant]
        meter = Counter()
        token = reference.METER.set(meter)
        begin = time.monotonic()
        try:
            graph, seeds, nodes, edges, header, filters = traverse(serve, self.graph, question, compatible)
            packing = None
            if graph is None:
                result = reference.bounded_payload("No matching nodes found.", cap, wire)
            elif atomic:
                result, packing = atomic_payload(serve, graph, nodes, edges, seeds, header,
                                                  native_budget, cap, inverse)
            else:
                raw = header + serve._subgraph_to_text(graph, nodes, edges, token_budget=native_budget, seeds=seeds)
                restored = reference.original_paths(raw, inverse)
                account("graph_path_mapping_input_characters", len(raw))
                account("graph_path_mapping_output_characters", len(restored))
                result = reference.bounded_payload(restored, cap, wire)
            encoded = wire(result)
            if len(encoded) > cap:
                raise AssertionError("Public tool budget exceeded")
            account("graph_complete_return_characters", len(result["graph_navigation"]))
            account("transport_serialized_output_characters", len(encoded))
        finally:
            elapsed = time.monotonic() - begin
            reference.METER.reset(token)
        # 以下为研究审计而非模型返回；不使用标准答案，不计入上下文。
        start_audit = time.monotonic()
        audit = {"variant": variant, "filters": filters, "seeds": list(seeds),
            "visited_nodes": sorted(nodes), "candidate_edges": [list(edge) for edge in edges],
            "packing": packing, "payload_sha256": digest(encoded),
            "payload_characters": len(encoded),
            "audit_seconds": None, "seconds": elapsed, "content": dict(meter)}
        audit["audit_seconds"] = time.monotonic() - start_audit
        return result, audit
