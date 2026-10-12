"""原版 Graphify 查询的只读适配；计量不改变评分、种子或遍历算法。"""
from __future__ import annotations

from collections import Counter
import contextvars
import functools
import json
from pathlib import Path
import re
import threading
import time


METER = contextvars.ContextVar("graphify_query_meter", default=None)
HOOK_LOCK = threading.Lock()


def length(value):
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (dict, list, tuple)):
        return len(json.dumps(value, ensure_ascii=False, default=str))
    return len(str(value)) if value is not None else 0


class Attributes(dict):
    """累计真正交给原版算法的属性值；重复访问重复计数。"""
    def account(self, value):
        meter = METER.get()
        if meter is not None:
            meter["graph_attribute_read_operations"] += 1
            meter["graph_attribute_read_characters"] += length(value)
        return value

    def get(self, key, default=None):
        return self.account(super().get(key, default))

    def __getitem__(self, key):
        return self.account(super().__getitem__(key))

    def items(self):
        for key, value in super().items():
            yield key, self.account(value)


def instrument_graph(graph):
    for node, data in list(graph._node.items()):
        if not isinstance(data, Attributes):
            graph._node[node] = Attributes(data)
    seen = {}
    for source, neighbors in graph._adj.items():
        for target, data in list(neighbors.items()):
            replacement = data if isinstance(data, Attributes) else seen.setdefault(id(data), Attributes(data))
            graph._adj[source][target] = replacement
            if graph.is_directed():
                graph._pred[target][source] = replacement
    return graph


def _install_hooks_unlocked():
    """包围固定版本函数；对中间图副本同样安装属性计数，不重跑检索。"""
    import graphify.serve as serve
    if getattr(serve, "_principia_meter_installed", False):
        return
    text_functions = {"_search_tokens", "_query_terms", "_trigrams", "_segment_chinese"}
    output_functions = {"_node_search_text", "_subgraph_to_text"}
    for name in text_functions | output_functions | {
        "_score_query", "_trigram_candidates", "_bfs", "_dfs", "_pick_seeds",
        "_traversal_view", "_filter_graph_by_context", "_complete_induced_edges", "_compute_idf",
    }:
        original = getattr(serve, name)
        @functools.wraps(original)
        def measured(*args, _name=name, _original=original, **kwargs):
            meter = METER.get()
            if meter is not None:
                meter["graph_internal_calls:" + _name] += 1
                if _name in text_functions and args:
                    meter["graph_text_input_characters:" + _name] += length(args[0])
                if _name == "_compute_idf":
                    graph, terms = args[:2]
                    missing = [t for t in terms if t not in graph.graph.get("_idf_cache", {})]
                    meter["graph_idf_uncached_terms"] += len(missing)
                    if missing:
                        meter["graph_idf_nodes_scanned"] += graph.number_of_nodes()
                if _name == "_complete_induced_edges":
                    meter["graph_induced_edge_input_nodes"] += len(args[1])
            result = _original(*args, **kwargs)
            if _name in {"_traversal_view", "_filter_graph_by_context"}:
                if meter is not None and result is not args[0]:
                    meter["graph_copy_node_records"] += result.number_of_nodes()
                    meter["graph_copy_edge_records"] += result.number_of_edges()
                instrument_graph(result)
            if meter is not None:
                if _name in output_functions:
                    meter["graph_text_output_characters:" + _name] += len(result)
                elif _name == "_trigram_candidates":
                    meter["graph_scoring_candidates"] += args[0].number_of_nodes() if result is None else len(result)
                elif _name == "_score_query":
                    meter["graph_ranked_nodes"] += len(result.ranked)
                elif _name in {"_bfs", "_dfs"}:
                    meter["graph_visited_nodes"] += len(result[0])
                    meter["graph_returned_induced_edges"] += len(result[1])
                elif _name == "_pick_seeds":
                    meter["graph_seed_nodes"] += len(result)
            return result
        setattr(serve, name, measured)
    # Graphify's BFS and induced-edge completion consume this iterator.
    import networkx as nx
    for cls in (nx.Graph, nx.DiGraph):
        original = cls.neighbors
        def neighbors(graph, node, _original=original):
            for neighbor in _original(graph, node):
                meter = METER.get()
                if meter is not None:
                    meter["graph_neighbor_visits"] += 1
                    meter["graph_neighbor_id_characters"] += len(str(neighbor))
                yield neighbor
        cls.neighbors = neighbors
    serve._principia_meter_installed = True


def install_hooks():
    with HOOK_LOCK:
        _install_hooks_unlocked()


class Backend:
    def __init__(self, path):
        from graphify.serve import _load_graph
        install_hooks()
        begin = time.monotonic()
        self.graph = instrument_graph(_load_graph(str(path)))
        self.initialization = {
            "seconds": time.monotonic() - begin,
            "content": {"graph_file_read_bytes": path.stat().st_size, "graph_file_read_operations": 1},
            "scope": "one persistent Graphify graph load per experiment arm; index caches subsequently charged when used",
        }

    def query(self, question, token_budget):
        from graphify.serve import _query_graph_text
        meter = Counter()
        token = METER.set(meter)
        begin = time.monotonic()
        try:
            raw = _query_graph_text(self.graph, question, mode="bfs", depth=2,
                                    token_budget=token_budget, graph_path="graphify-out/graph.json")
        finally:
            METER.reset(token)
        meter["graph_complete_return_characters"] += len(raw)
        return raw, {"seconds": time.monotonic() - begin, "content": dict(meter)}


def original_paths(text, inverse):
    """只改返回的src/at字段，不重标图节点、重新评分或补充原文内容。"""
    text = re.sub(r"(src=)(.*?)( loc=)",
                  lambda m: m[1] + inverse.get(m[2], m[2]) + m[3], text)
    return re.sub(r"(at=)(\S+?)(:L\d+\b)",
                  lambda m: m[1] + inverse.get(m[2], m[2]) + m[3], text)


def bounded_payload(raw, cap, serialize):
    payload = {"status": "no_match" if raw == "No matching nodes found." else "ok",
               "graph_navigation": raw, "truncated": False,
               "evidence": "derived_navigation_only_read_original_sources"}
    if len(serialize(payload)) <= cap:
        return payload
    payload.update(graph_navigation="", truncated=True)
    for line in raw.splitlines(keepends=True):
        proposed = {**payload, "graph_navigation": payload["graph_navigation"] + line}
        if len(serialize(proposed)) > cap:
            break
        payload = proposed
    return payload
