"""以冻结图验证计数器输出等价、路径还原和公共预算；不调用回答模型。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    root = args.run.resolve()
    sys.path.insert(0, str(root))
    import navigation_qa as qa
    from graphify_query_backend import Backend, bounded_payload, original_paths
    from graphify.serve import _load_graph, _query_graph_text
    queries = ["JWL 状态方程 教程配置", "movingCone dynamicMeshDict", "自适应网格细化 AMR 配置条件",
               "multicomponentMixture phaseProperties", "no_such_baseline_symbol_378921"]
    expected = {}
    for group in ("native", "text_adapter"):
        path = root / group / "graphify-out/graph.json"
        graph = _load_graph(str(path))
        for query in queries:
            expected[group, query] = _query_graph_text(graph, query, mode="bfs", depth=2,
                                      token_budget=1437, graph_path="graphify-out/graph.json")
    results = []
    for group in ("native", "text_adapter"):
        backend = Backend(root / group / "graphify-out/graph.json")
        inverse = qa.read(root / group / "path-map.json")
        for query in queries:
            raw, cost = backend.query(query, 1437)
            if raw != expected[group, query]:
                raise ValueError("Instrumentation changed native query output")
            repeated, _ = backend.query(query, 1437)
            if repeated != raw:
                raise ValueError("Native cache changed the output")
            result = bounded_payload(original_paths(raw, inverse), 6000, qa.wire)
            if len(qa.wire(result)) > 6000:
                raise ValueError("Hard budget exceeded")
            results.append({"group": group, "query": query, "native_equivalent": True,
                            "cold_warm_output_equal": True, "result": result, "cost": cost})
    output = root / "preflight" / f"query-parity-{time.time_ns()}.json"
    qa.write(output, {"status": "PASS", "llm_calls": 0, "queries": results,
                     "note": "Metered vs unmetered official core output equality; not retrieval accuracy."})
    print(qa.wire({"status": "PASS", "query_checks": len(results), "artifact": str(output)}))


if __name__ == "__main__":
    main()
