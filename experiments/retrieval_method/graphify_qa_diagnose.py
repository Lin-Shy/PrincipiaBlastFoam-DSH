"""离线重放已保存图查询，定位原生 Graphify 返回不稳定性；不调用模型。"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--group", default="text_adapter")
    parser.add_argument("--session", default="Q007-p1--graph_first--r1")
    args = parser.parse_args()
    sys.path.insert(0, str(args.run))
    from graphify_query_backend import Backend, bounded_payload, original_paths
    import navigation_qa as qa
    qa.verify(args.run)
    root = args.run / args.group
    data = qa.read(root/"sessions"/args.session/"result.json")
    inverse = qa.read(root/"path-map.json")
    backend = Backend(root/"graphify-out/graph.json")
    checks = []
    used = 0
    for event in data["events"]:
        if "result" not in event:
            continue
        audit = event["accounting"].get("native_query_audit")
        if audit:
            raw, cost = backend.query(audit["query"], audit["token_budget"])
            restored = original_paths(raw, inverse)
            cap = min(6000, 24000-used)
            actual = bounded_payload(restored, cap, qa.wire)
            checks.append({"step": event["step"], "raw_equal": raw == audit["raw_native_return"],
                "payload_equal": actual == event["result"], "original_length": len(audit["raw_native_return"]),
                "current_length": len(raw), "hash_seed": os.environ.get("PYTHONHASHSEED", "random"),
                "raw_diff": list(difflib.unified_diff(audit["raw_native_return"].splitlines(), raw.splitlines())),
                "payload_diff": list(difflib.unified_diff(qa.wire(event["result"]).splitlines(), qa.wire(actual).splitlines())),
                "actual_native_output": raw, "cost": cost})
        used += event["returned_characters"]
    output = args.run/"diagnostics"/("native-replay-"+str(time.time_ns())+".json")
    qa.write(output, {"llm_calls": 0, "group": args.group, "session": args.session,
                     "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "checks": checks})
    print(qa.wire({"output": str(output), "checks": [{k:v for k,v in c.items() if k not in ("actual_native_output","cost","payload_diff")} for c in checks]}))


if __name__ == "__main__":
    main()
