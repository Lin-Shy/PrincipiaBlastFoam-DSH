"""逐臂重放冻结原生检索，不读gold、不调用在线模型、不改写原结果。"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time


def normalized(value):
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()
                if k not in {"seconds", "graph_scan_seconds_and_ranking"} and not k.endswith("_seconds")}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def differences(left, right, path="", tolerance=1e-6):
    if type(left) is not type(right):
        return [path + ":type"]
    if isinstance(left, dict):
        if set(left) != set(right):
            return [path + ":keys"]
        return [d for key in left for d in differences(left[key], right[key], path + "/" + key, tolerance)]
    if isinstance(left, list):
        if len(left) != len(right):
            return [path + ":length"]
        return [d for i, (a, b) in enumerate(zip(left, right)) for d in differences(a, b, path + "/" + str(i), tolerance)]
    if isinstance(left, float):
        return [] if math.isclose(left, right, rel_tol=0, abs_tol=tolerance) else [path + ":float"]
    return [] if left == right else [path + ":value"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--arm", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    root = args.root.resolve()
    if args.output.exists():
        raise FileExistsError("new native replay version required")
    sys.path.insert(0, str(root / "runtime"))
    from chapter2_formal_runtime import verify, load, save, sha, jobs, compiled, SELF_ARMS, BASE_ARMS
    protocol, protocol_sha = verify(root, require_snapshot=False)
    if args.arm not in protocol["native_arms"]:
        raise ValueError("frozen native arm required")
    if not (root / "completion" / ("native--" + args.arm + ".json")).exists():
        raise ValueError("finish arm before native replay")
    if args.arm == "e5":
        os.environ["HF_HUB_OFFLINE"] = "1"
        import torch
        import sentence_transformers
    if args.arm in {"graphify_native", "graphify_text_adapter"}:
        sys.path.insert(0, protocol["paths"]["graphify_upstream"])
    from chapter2_production_guard import install
    guard = install(offline=True, allow_test_public=True)
    corpus = Path(protocol["paths"]["corpus"])
    manifest = Path(protocol["public_inputs"]["corpus_manifest"]["path"])
    if args.arm in SELF_ARMS:
        from chapter2_graph_retriever import GraphRetriever
        engine = GraphRetriever(protocol["public_inputs"]["self_graph"]["path"], corpus, SELF_ARMS[args.arm], manifest)
    else:
        from chapter2_baseline_native import NoGraphBM25, DenseE5, GraphifyNative
        if args.arm == "no_graph":
            engine = NoGraphBM25(corpus, manifest)
        elif args.arm == "e5":
            engine = DenseE5(corpus, manifest, Path(protocol["paths"]["e5_index"]))
        else:
            graph = Path(protocol["public_inputs"][args.arm + "_graph"]["path"])
            mapping = Path(protocol["public_inputs"]["graphify_path_map"]["path"]) if args.arm == "graphify_text_adapter" else None
            engine = GraphifyNative(corpus, manifest, graph, mapping)
    from chapter2_canonical_delivery import canonicalize, render
    rows = []
    for key, repeat, question in jobs(protocol):
        file = root / "native" / args.arm / (key + ".json")
        original = load(file)
        plan, plan_sha = compiled(root, key, question, protocol_sha)
        if original["question"] != question or original["protocol_sha256"] != protocol_sha or original["planner_compiled_sha256"] != plan_sha:
            raise ValueError("native replay provenance drift")
        begin = time.monotonic()
        if args.arm in SELF_ARMS:
            native = engine.rank(question["question"], plan["plan"])
            packet = engine.read_native(native)
        else:
            packet, diagnostic = engine.query(question["question"], plan["plan"], 64)
            native = None
        seconds = time.monotonic()-begin
        units = canonicalize(packet, seconds)
        replay = {"native": native, "mapped_native": packet, "canonical_units": units,
            "deliveries": {str(cap): render(units, cap) for cap in protocol["budgets"]},
            "answer_delivery": render(units, protocol["source_character_cap"])}
        saved = {key: original[key] for key in replay}
        drift = differences(normalized(replay), normalized(saved))
        rows.append({"key": key, "response_sha256": sha(file), "status": "passed" if not drift else "drift",
            "drift_fields": drift[:50], "drift_field_count": len(drift), "replay_seconds": seconds})
        print("REPLAY", args.arm, key, rows[-1]["status"], flush=True)
    output = {"schema": "formal-native-source-context-replay-v1", "arm": args.arm, "protocol_sha256": protocol_sha,
        "implementation_sha256": sha(Path(__file__)), "guard": guard, "online_llm_calls": 0,
        "e5_encoder_calls": len(rows) if args.arm == "e5" else 0, "rows": rows,
        "queries": len(rows), "passes": sum(r["status"] == "passed" for r in rows),
        "drifts": sum(r["status"] != "passed" for r in rows), "float_absolute_tolerance": 1e-6,
        "excluded_transient_fields": ["seconds", "*_seconds", "graph_scan_seconds_and_ranking"],
        "limits": "all ranks, routes, source/hash/lines/scopes/renderedtext/characters checked; transientseconds excluded; E5 fresh encoder forward is not an onlineLLM call; no gold, no quality grading, no original artifact overwrite"}
    save(args.output, output)
    if output["drifts"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
