"""冻结并离线消融历史 Graphify 查询；没有模型调用和凭据入口。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import random
import re
import sys
import time

try:
    from . import graphify_query_variants as variants
except ImportError:
    import graphify_query_variants as variants


class IO:
    def __init__(self):
        self.counts = Counter()

    def raw(self, path):
        raw = path.read_bytes()
        self.counts.update(read_operations=1, read_bytes=len(raw))
        return raw

    def read(self, path):
        return json.loads(self.raw(path))

    def write(self, path, value):
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(raw)
        self.counts.update(write_operations=1, write_bytes=len(raw))

    def copy(self, source, target):
        raw = self.raw(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(raw)
        self.counts.update(write_operations=1, write_bytes=len(raw))


def runtime_identity():
    return {"pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "hash_probe": hash("Principia Graphify QA frozen seed"), "python": sys.version}


def contained(root, name):
    path = root / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Manifest path escapes root")
    return path


def verify_files(root, files, io):
    for name, expected in files.items():
        if variants.digest(io.raw(contained(root, name))) != expected:
            raise ValueError("Frozen artifact changed: " + name)


def verify_parent(root, io):
    protocol = io.read(root / "protocol.json")
    if runtime_identity() != protocol["runtime_identity"] or os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("Use the frozen Python interpreter with PYTHONHASHSEED=0")
    verify_files(root, protocol["files"], io)
    import graphify
    verify_files(Path(graphify.__file__).parent,
                 protocol["graphify_identity"]["implementation_files_sha256"], io)
    return protocol


def source_paths(payload):
    text = payload["graph_navigation"]
    return sorted(set(re.findall(r"src=(.*?) loc=", text)) |
                  set(re.findall(r"at=(\S+?):L\d+\b", text)))


def prepare(args):
    begin = time.monotonic()
    source, target = args.source_run.resolve(), args.run.resolve()
    if target.exists():
        raise FileExistsError("Choose a fresh experiment directory")
    io = IO()
    protocol = verify_parent(source, io)
    reference = Path(variants.reference.__file__)
    if io.raw(reference) != io.raw(source / "graphify_query_backend.py"):
        raise ValueError("Metered reference backend differs from frozen QA backend")
    inputs, bindings = [], {}
    for group in ["native", "text_adapter"]:
        limits = io.read(source / group / "protocol.json")["limits"]
        for path in sorted((source / group / "sessions").glob("*/result.json")):
            raw = io.raw(path)
            data = json.loads(raw)
            bindings[path.relative_to(source).as_posix()] = variants.digest(raw)
            used = 0
            for event in data["events"]:
                if "result" not in event:
                    continue
                audit = event["accounting"].get("native_query_audit")
                if audit:
                    cap = min(limits["per_tool_characters"], limits["returned_characters"]-used)
                    if audit["token_budget"] != max(100, (cap-250)//4):
                        raise ValueError("Historical query budget inconsistent")
                    composed = "\n".join(x for x in [data["question"],
                        event["action"].get("translation", ""), event["action"].get("query", "")] if x)
                    if composed != audit["query"]:
                        raise ValueError("Historical full question composition changed")
                    tool_path = path.parent / "tool_events" / f"step-{event['step']:02d}.json"
                    tool_raw = io.raw(tool_path)
                    if json.loads(tool_raw)["result"] != event["result"]:
                        raise ValueError("Historical event/result disagree")
                    bindings[tool_path.relative_to(source).as_posix()] = variants.digest(tool_raw)
                    inputs.append({"id": group+"/"+path.parent.name+"/"+str(event["step"]),
                        "group": group, "session": path.parent.name, "step": event["step"],
                        "question_id": data["id"], "query": audit["query"], "cap": cap,
                        "native_budget": audit["token_budget"], "expected_payload": event["result"]})
                used += event["returned_characters"]
    if not inputs:
        raise ValueError("No historical graph queries")
    target.mkdir(parents=True)
    io.copy(Path(__file__), target / "code/replay.py")
    io.copy(Path(variants.__file__), target / "code/graphify_query_variants.py")
    io.copy(reference, target / "code/graphify_query_backend.py")
    io.copy(args.plan.resolve(), target / "plan.md")
    for group in ["native", "text_adapter"]:
        io.copy(source / group / "graphify-out/graph.json", target / group / "graph.json")
        io.copy(source / group / "path-map.json", target / group / "path-map.json")
    io.write(target / "queries.json", inputs)
    files = {path.relative_to(target).as_posix(): variants.digest(io.raw(path))
             for path in sorted(target.rglob("*")) if path.is_file()}
    io.write(target / "manifest.json", {"schema": "graphify-query-factorial-v1", "files": files,
        "source_run": str(source), "source_protocol_sha256": variants.digest(io.raw(source / "protocol.json")),
        "source_result_bindings": bindings, "runtime_identity": runtime_identity(),
        "variants": variants.VARIANTS, "query_count": len(inputs), "shuffle_seed": 20260909,
        "model_calls": 0, "holdout_unlocked": False, "gold_used_by_query": False,
        "scope": "fixed historical queries; not new QA, no source evidence credited",
        "graphify_identity": protocol["graphify_identity"],
        "preparation_seconds": time.monotonic()-begin, "preparation_io_before_manifest_write": dict(io.counts)})
    print(variants.wire({"prepared": str(target), "queries": len(inputs), "variants": list(variants.VARIANTS)}))


def verify(run, io):
    manifest = io.read(run / "manifest.json")
    if runtime_identity() != manifest["runtime_identity"]:
        raise ValueError("Frozen runtime mismatch")
    verify_files(run, manifest["files"], io)
    source = Path(manifest["source_run"])
    if variants.digest(io.raw(source / "protocol.json")) != manifest["source_protocol_sha256"]:
        raise ValueError("Parent protocol identity changed")
    verify_parent(source, io)
    verify_files(source, manifest["source_result_bindings"], io)
    return manifest


def execute(args):
    run, output = args.run.resolve(), args.output.resolve()
    if output.exists():
        raise FileExistsError("Do not overwrite an earlier replay")
    if Path(__file__).resolve() != run / "code/replay.py":
        raise ValueError("Execute the frozen replay driver")
    begin = time.monotonic()
    io = IO()
    manifest = verify(run, io)
    verified_seconds = time.monotonic()-begin
    queries = io.read(run / "queries.json")
    maps = {group: io.read(run / group / "path-map.json") for group in ["native", "text_adapter"]}
    output.mkdir(parents=True)
    io.write(output / "started.json", {"status": "in_flight", "pid": os.getpid(),
        "manifest_sha256": variants.digest(io.raw(run / "manifest.json")), "model_calls": 0})
    initialized = time.monotonic()
    backends = {(group, variant): variants.Backend(run / group / "graph.json")
                for group in maps for variant in variants.VARIANTS}
    initializations = {group+"/"+variant: backend.initialization
                       for (group, variant), backend in backends.items()}
    initialization_seconds = time.monotonic()-initialized
    rng = random.Random(manifest["shuffle_seed"])
    rows, gates = [], []
    totals = defaultdict(Counter)
    input_order = list(queries)
    rng.shuffle(input_order)
    try:
        for index, query in enumerate(input_order, 1):
            order = list(variants.VARIANTS)
            rng.shuffle(order)
            outcomes = {}
            for mode in order:
                payload, audit = backends[query["group"], mode].payload(query["query"],
                    query["native_budget"], query["cap"], maps[query["group"]], mode)
                outcomes[mode] = {"payload": payload, "audit": audit}
            checks = {"reference_payload_identical": outcomes["original"]["payload"] == query["expected_payload"],
                "seeds_unchanged": len({variants.wire(value["audit"]["seeds"]) for value in outcomes.values()}) == 1,
                "public_budgets": all(len(variants.wire(v["payload"])) <= query["cap"] for v in outcomes.values())}
            for left, right in [("original", "atomic"), ("compatible", "combined")]:
                checks[left+"_"+right+"_same_candidates"] = all(outcomes[left]["audit"][k] == outcomes[right]["audit"][k]
                    for k in ["seeds", "visited_nodes", "candidate_edges"])
            before_sources = set(source_paths(outcomes["original"]["payload"]))
            for mode, value in outcomes.items():
                payload, audit = value["payload"], value["audit"]
                shown = payload["graph_navigation"].splitlines()
                packing = audit["packing"]
                if packing:
                    checks[mode+"_endpoint_integrity"] = all(
                        edge["line"] in shown and all(packing["endpoint_records"][node] in shown for node in edge["endpoints"])
                        for edge in packing["shown_edges"])
                    checks[mode+"_body_budget"] = packing["body_characters"] + packing["reserved_notice_characters"] <= query["native_budget"]*3
                current_sources = set(source_paths(payload))
                stats = {"queries": 1, "shown_nodes": sum(s.startswith("NODE ") for s in shown),
                    "shown_edges": sum(s.startswith("EDGE ") for s in shown),
                    "edge_bearing_outputs": int(any(s.startswith("EDGE ") for s in shown)),
                    "zero_expansion": int(len(audit["visited_nodes"]) == len(audit["seeds"])),
                    "internal_edges": len(audit["candidate_edges"]),
                    "dropped_unsupported_filters": len(audit["filters"]["dropped"]),
                    "returned_characters": len(variants.wire(payload)), "query_seconds": audit["seconds"],
                    "audit_seconds": audit["audit_seconds"], "distinct_sources_per_query_sum": len(current_sources),
                    "original_sources_retained": len(current_sources & before_sources),
                    "original_sources_lost": len(before_sources-current_sources),
                    "new_sources": len(current_sources-before_sources),
                    "queries_losing_original_sources": int(bool(before_sources-current_sources))}
                totals[query["group"]+"/"+mode].update(stats)
                value["stats"] = stats
            gate = {"id": query["id"], "checks": checks, "pass": all(checks.values())}
            gates.append(gate)
            destination = output / "queries" / (query["id"].replace("/", "__") + ".json")
            io.write(destination, {"input": query, "outcomes": outcomes, "gate": gate})
            rows.append({"id": query["id"], "variants": {mode: {
                "payload_sha256": value["audit"]["payload_sha256"],
                "candidates_sha256": variants.digest(variants.wire({key: value["audit"][key]
                    for key in ["seeds", "visited_nodes", "candidate_edges"]}))}
                for mode, value in outcomes.items()}})
            if not gate["pass"]:
                raise AssertionError("Query gate failed: " + query["id"])
            if index % 10 == 0:
                print(variants.wire({"queries_checked": index, "total": len(queries)}), flush=True)
        post_start = time.monotonic()
        verify(run, io)
        post_seconds = time.monotonic()-post_start
        io.write(output / "summary.json", {"status": "PASS", "model_calls": 0,
            "queries": len(queries), "query_variant_evaluations": len(rows)*len(variants.VARIANTS),
            "totals": dict(totals), "gates": gates, "identities": sorted(rows, key=lambda row: row["id"]),
            "initializations": initializations, "initialization_seconds": initialization_seconds,
            "pre_verification_seconds": verified_seconds, "post_verification_seconds": post_seconds,
            "elapsed_before_summary_seconds": time.monotonic()-begin,
            "io_before_summary": dict(io.counts), "limits": [
                "No new model answers or answer-quality scores; only historical-query counterfactuals.",
                "Candidate and source counts are navigation diagnostics, not raw-evidence recall or relation correctness.",
                "Detailed overlapping work counters are in per-query audits; do not add them as API tokens.",
                "Process startup/import/OS activity is not fully instrumented and is not counted as zero.",
                "No construction, ordinary search, raw-source tool reads, or LLM calls in this offline phase."]})
    except BaseException as error:
        io.write(output / "failure.json", {"status": "FAIL", "type": type(error).__name__,
            "message": str(error), "completed": len(rows), "model_calls": 0,
            "elapsed_seconds": time.monotonic()-begin, "io": dict(io.counts)})
        raise
    print(variants.wire({"status": "PASS", "output": str(output), "queries": len(queries), "model_calls": 0}))


def compare(args):
    io = IO()
    left, right = io.read(args.left / "summary.json"), io.read(args.right / "summary.json")
    same = left["identities"] == right["identities"]
    record = {"status": "PASS" if same else "FAIL", "equal_payloads_and_candidates": same,
        "left_sha256": variants.digest(io.raw(args.left / "summary.json")),
        "right_sha256": variants.digest(io.raw(args.right / "summary.json")),
        "queries": left["queries"], "model_calls": 0,
        "scope": "separate-process deterministic query repeat, not independent QA replication"}
    io.write(args.output, record)
    print(variants.wire(record))
    if not same:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source-run", type=Path, required=True)
    prep.add_argument("--run", type=Path, required=True)
    prep.add_argument("--plan", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--run", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    comp = commands.add_parser("compare")
    comp.add_argument("--left", type=Path, required=True)
    comp.add_argument("--right", type=Path, required=True)
    comp.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "run": execute, "compare": compare}[args.command](args)


if __name__ == "__main__":
    main()
