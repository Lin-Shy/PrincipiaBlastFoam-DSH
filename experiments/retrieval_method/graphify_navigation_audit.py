"""冻结并重复执行来源驱动的检索契约检查；不是自然语言问答评测。"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

if __package__:
    from . import graphify_evidence_search as search
else:
    import graphify_evidence_search as search

cross = search.cross


def prepare(relations, output):
    if output.exists():
        raise FileExistsError("choose a new snapshot directory")
    started = time.perf_counter()
    manifest_raw = (relations / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    layer_raw = (relations / "layer.json").read_bytes()
    if cross.sha(layer_raw) != manifest["artifacts"]["layer.json"]:
        raise ValueError("relation layer drift")
    layer = json.loads(layer_raw)
    modules = [sys.modules[__name__], search, cross, cross.structure, cross.structure.structural_parser]
    code = {Path(m.__file__).name: Path(m.__file__).read_bytes() for m in modules}
    # Do not validate a frozen relation graph using an unnoticed new rule version.
    for name in ("graphify_cross_source.py", "graphify_structure.py", "navigation_structure_parser.py"):
        if cross.sha(code[name]) != manifest["artifacts"]["code/" + name]:
            raise ValueError("relation rule implementation changed; rebuild a new layer first")
    queries = []
    for r in layer["relations"]:
        model = layer["definitions"][r["target"]]["name"]
        queries.append({"id": r["id"], "query": model + (" " + r["parameter"] if r["parameter"] else ""),
            "case": r["scope"]["case_directory"],
            "dictionary": r["conditions"]["selector_path"].rsplit("/", 1)[0],
            "purpose": "source-derived exact-name/explicit-scope retrieval contract, not QA"})
    products = {"queries.json": cross.encoded(queries),
        "relations/manifest.json": manifest_raw, "relations/layer.json": layer_raw,
        **{"code/" + n: b for n, b in code.items()}}
    frozen = {"schema": "principia-navigation-contract-audit-v1", "relation_manifest_sha256": cross.sha(manifest_raw),
        "relation_id": manifest["relation_id"], "cap": 6000, "seed_limit": 32,
        "conditions": ["with_relations", "without_relations"],
        "artifacts": {n: cross.sha(b) for n, b in products.items()},
        "model_calls": 0, "QA_evaluated": False, "holdout_opened": False,
        "limits": "Queries derived only from accepted source relations to test the navigation contract; not independent semantic accuracy, generalization or a QA benchmark."}
    products["manifest.json"] = cross.encoded(frozen)
    output.mkdir(parents=True)
    for name, content in products.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (output / "preparation_accounting.json").write_bytes(cross.encoded({
        "explicit_read_operations": 2 + len(code), "explicit_read_bytes": len(manifest_raw) + len(layer_raw) + sum(map(len, code.values())),
        "written_bytes_excluding_accounting": sum(map(len, products.values())),
        "wall_seconds_before_accounting_write": time.perf_counter() - started, "model_calls": 0}))
    print(search.compact({"snapshot": str(output), "manifest_sha256": cross.sha(products["manifest.json"]),
                          "queries": len(queries), "model_calls": 0}))


def checks(payload, audit, engine, requested, with_relations):
    failures = []
    if len(search.compact(payload)) > audit["cap"]:
        failures.append("budget")
    for group in payload["groups"]:
        if group["case"] and group["case"] != requested["case"]:
            failures.append("case_scope")
        if group["kind"] == "cross_source":
            paths = {payload["sources"][payload["evidence"][eid]["source"]] for eid in group["evidence"]}
            if {cross.structure.source_category(p) for p in paths} != {"manual", "tutorial"}:
                failures.append("one_sided_group")
            for rid in audit["returned_canonical_relations"][group["id"]]:
                relation = next(r for r in engine.layer["relations"] if r["id"] == rid)
                for a in relation["manual_evidence"] + relation["tutorial_evidence"]:
                    if not any(payload["sources"][e["source"]] == a["path"] and e["start"] <= a["start"] <= a["end"] <= e["end"]
                               for eid in group["evidence"] for e in [payload["evidence"][eid]]):
                        failures.append("incomplete_required_anchor")
    for e in payload["evidence"].values():
        p = payload["sources"][e["source"]]
        expected = "".join(f"{i}: {line}" for i, line in enumerate(engine.lines[p][e["start"] - 1:e["end"]], e["start"]))
        if expected != e["text"]:
            failures.append("verbatim_line_mismatch")
    returned = {r for rs in audit["returned_canonical_relations"].values() for r in rs}
    if with_relations and requested["id"] not in returned:
        failures.append("requested_literal_relation_not_returned")
    if not with_relations and returned:
        failures.append("relation_in_off_condition")
    return sorted(set(failures))


def run(snapshot, output):
    if output.exists():
        raise FileExistsError("preserve previous run")
    start = time.perf_counter()
    manifest_raw = (snapshot / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    integrity = Counter(read_operations=1, read_bytes=len(manifest_raw))
    products = {}
    for name, digest in manifest["artifacts"].items():
        raw = (snapshot / name).read_bytes()
        integrity["read_operations"] += 1
        integrity["read_bytes"] += len(raw)
        if cross.sha(raw) != digest:
            raise ValueError("frozen audit input drift")
        products[name] = raw
    if Path(__file__).resolve().parent != (snapshot / "code").resolve():
        raise ValueError("run the frozen code from snapshot/code")
    engine = search.Engine.load(snapshot / "relations")
    queries = json.loads(products["queries.json"])
    results, work, failures = [], Counter(), Counter()
    seen_checks = 0
    for q in queries:
        for enabled in (False, True):
            payload, audit = engine.query(q["query"], case=q["case"], dictionary=q["dictionary"],
                cap=manifest["cap"], seed_limit=manifest["seed_limit"], with_relations=enabled)
            errors = checks(payload, audit, engine, q, enabled)
            if enabled:
                more, more_audit = engine.query(q["query"], case=q["case"], dictionary=q["dictionary"],
                    cap=manifest["cap"], seed_limit=manifest["seed_limit"], seen_groups=audit["returned_group_ids"])
                if set(audit["returned_group_ids"]) & {g["id"] for g in more["groups"]}:
                    errors.append("seen_group_repeated")
                seen_checks += 1
                results.append({"query_id": q["id"], "condition": "incremental", "payload": more, "audit": more_audit})
                work.update(more_audit["work"])
            failures.update(errors)
            work.update(audit["work"])
            results.append({"query_id": q["id"], "condition": "with_relations" if enabled else "without_relations",
                "payload": payload, "audit": audit, "checks": errors})
    identities = [{"query": r["query_id"], "condition": r["condition"], "payload_sha256": cross.sha(cross.encoded(r["payload"])),
                   "seed_ids": r["audit"]["seed_ids"], "candidates": r["audit"]["candidate_group_ids"]} for r in results]
    summary = {"status": "PASS" if not failures else "FAIL", "failures": dict(failures),
        "source_derived_queries": len(queries), "query_evaluations_including_incremental": len(results),
        "incremental_checks": seen_checks, "results_identity": cross.sha(cross.encoded(identities)),
        "work": dict(work), "initialization": engine.initialization, "integrity_reads": dict(integrity),
        "returned_characters_all_queries": sum(r["audit"]["returned_characters"] for r in results),
        "wall_seconds_before_output_write": time.perf_counter() - start,
        "model_requests": 0, "model_tokens": 0, "QA_evaluated": False,
        "limits": manifest["limits"] + " Test-checker CPU and integrity reads are included in command wall, not separately timed; import/OS I/O not fully traced."}
    output.mkdir(parents=True)
    serialized = {name: cross.encoded(content) for name, content in
                  {"results.json": results, "identities.json": identities, "summary.json": summary}.items()}
    for name, content in serialized.items():
        (output / name).write_bytes(content)
    (output / "accounting.json").write_bytes(cross.encoded({
        "wall_seconds_including_main_output_writes": time.perf_counter() - start,
        "written_bytes_excluding_accounting": sum(map(len, serialized.values())),
        "integrity_reads": dict(integrity), "initialization": engine.initialization,
        "query_work": dict(work), "model_calls": 0, "model_tokens": 0}))
    print(search.compact({k: summary[k] for k in ("status", "failures", "query_evaluations_including_incremental", "results_identity", "model_requests")}))


def compare(first, second, output):
    if output.exists():
        raise FileExistsError("preserve comparison output")
    a, b = (first / "identities.json").read_bytes(), (second / "identities.json").read_bytes()
    checks = [json.loads((p / "summary.json").read_text())["status"] for p in (first, second)]
    result = {"status": "PASS" if a == b and checks == ["PASS", "PASS"] else "FAIL", "identical_results": a == b,
        "first": str(first), "second": str(second), "per_run_status": checks,
        "comparisons": len(json.loads(a)), "model_calls": 0, "independent_QA_repeats": 0}
    output.write_bytes(cross.encoded(result))
    print(search.compact(result))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--relations", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("run")
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("compare")
    p.add_argument("--first", type=Path, required=True)
    p.add_argument("--second", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.command == "prepare":
        prepare(args.relations.resolve(), args.output.resolve())
    elif args.command == "run":
        run(args.snapshot.resolve(), args.output.resolve())
    else:
        compare(args.first.resolve(), args.second.resolve(), args.output.resolve())
