"""第2章统一八配置多步问答。独立冻结，不修改历史运行或读取留出题。"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import random
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import graphify_qa as base
import navigation_qa as qa
import graphify_evidence_search as evidence

GROUPS = {**base.GROUPS, "GN": ["graph_first"], "GH": ["graph_first"],
          "GH_evidence": ["graph_first"]}


def prompt(method):
    common = base.prompt(method)
    common += "原文text逐行以行号标记；evidence_id绑定语料版本、路径及完整行范围。引用仍用path/start/end/supports。\n"
    if method != "no_graph":
        common += "locate可能返回导航文本或含sources路径映射及evidence原文的证据组；只有原文可支持主张。\n"
    return common


class Session(base.Session):
    def source_item(self, path, start, end):
        return {"path": path, "start": start, "end": end,
                "evidence_id": qa.digest(qa.wire([self.e.manifest[path]["sha256"], path, start, end]))[:24],
                "text": "\n".join(f"{n}: {self.e.files[path][n-1]}" for n in range(start, end+1)),
                "complete_range": True, "line_numbered": True}

    def observe(self, result):
        items = list(result.get("items", []))
        raw_evidence = result.get("evidence", {})
        for item in (raw_evidence.values() if isinstance(raw_evidence, dict) else []):
            items.append({**item, "path": result["sources"][item["source"]], "line_numbered": True})
        for item in items:
            if not item.get("text") or item.get("path") not in self.e.files:
                continue
            path, start, end = item["path"], item["start"], item["end"]
            if not 1 <= start <= end <= len(self.e.files[path]):
                raise ValueError("invalid original evidence range")
            expected = "\n".join(f"{n}: {self.e.files[path][n-1]}" for n in range(start, end+1))
            if item.get("line_numbered") and item["text"].rstrip("\n") != expected.rstrip("\n"):
                raise ValueError("numbered evidence differs from corpus")
            if not item.get("line_numbered"):
                raise ValueError("unrecognized evidence representation")
            self.seen.setdefault(path, {}).update({str(n): self.e.files[path][n-1] for n in range(start, end+1)})

    def dispatch(self, action, cap):
        if self.e.variant != "GH_evidence" or action.get("action") != "locate":
            return super().dispatch(action, cap)
        begin = time.monotonic()
        identity = qa.wire({k: v for k, v in action.items() if k != "reason"})
        repeat = identity in self.seen_requests
        self.seen_requests.add(identity)
        self.calls["locate"] += 1
        self.graph_attempted = True
        audit, initialization = None, None
        try:
            translation, gap = action.get("translation", ""), action.get("query", "")
            if not isinstance(translation, str) or not isinstance(gap, str):
                raise ValueError("invalid query")
            query = "\n".join(x for x in (self.question, translation, gap) if x)
            if len(query) > 12000:
                raise ValueError("graph query too long")
            with self.e.graph_lock:
                if self.e.backend is None:
                    protocol = qa.read(self.e.run / "protocol.json")
                    self.e.backend = evidence.Engine.load(Path(protocol["relation_root"]))
                    initialization = self.e.backend.initialization
                    qa.write(self.e.run / f"runtime-initialization-{time.time_ns()}.json", initialization)
                result, audit = self.e.backend.query(query, cap=cap)
            self.observe(result)
        except (ValueError, KeyError, TypeError) as error:
            result = {"status": "tool_error", "reason": str(error)[:200]}
        if len(qa.wire(result)) > cap:
            raise AssertionError("evidence tool exceeded public budget")
        return result, {"seconds": time.monotonic()-begin, "repeat": repeat,
                        "content": audit["work"] if audit else {}, "evidence_query_audit": audit,
                        "initialization": initialization, "initialization_time_included": initialization is not None}


def install():
    base.install()
    qa.Session, qa.prompt = Session, prompt


def prepare(args):
    # Reuse corpus/gold identity validation and the original five frozen arms.
    base.prepare(args)
    root = args.run.resolve()
    structure = args.structure.resolve()
    relation = args.relations.resolve()
    evidence.Engine.load(relation)  # validates all alignment, source and construction identities
    for group in ("GN", "GH", "GH_evidence"):
        target = root / group
        shutil.copytree(root / "control", target)
        structure_manifest = qa.read(structure / "manifest.json")
        parent_variant = structure_manifest.get("parent_variant", "native")
        if parent_variant == "text_adapter":
            mapping = qa.read(args.archive.resolve() / "text_adapter_manifest.json")["path_map"]
            qa.write(target / "path-map.json", {adapted: original for original, adapted in mapping.items()})
        if group != "GH_evidence":
            (target / "graphify-out").mkdir()
            shutil.copy2(structure / group / "graph.json", target / "graphify-out/graph.json")
        protocol = qa.read(target / "protocol.json")
        protocol.update(arm=group, methods=GROUPS[group], graph_baseline=None,
                        parent_graphify_variant=parent_variant,
                        graph_query="same native Graphify query as baseline" if group != "GH_evidence" else "scoped-evidence-search-v1, default seed_limit=32; parent metadata hierarchy; not GH edge traversal",
                        structure_manifest_sha256=qa.digest((structure / "manifest.json").read_bytes()))
        if group == "GH_evidence":
            protocol.update(relation_root=str(relation), relation_manifest_sha256=qa.digest((relation / "manifest.json").read_bytes()))
        qa.write(target / "protocol.json", protocol)
    # Keep executable source in project; archive exact runtime copies for replay.
    for path in Path(__file__).parent.glob("*.py"):
        shutil.copy2(path, root / path.name)
    shutil.copy2(Path(__file__), root / "runner.py")
    for group, methods in GROUPS.items():
        target = root / group
        protocol = qa.read(target / "protocol.json")
        protocol.update(schema="principia-leaderboard-arm-v1", methods=methods,
                        prompts={m: prompt(m) for m in methods}, graph_evidence="only verified numbered raw source lines credited",
                        failure_policy="three transport attempts per invocation; maximum nine identical-request attempts; provider failures retained; no answer-quality retries; four consecutive no-HTTP network errors open a process circuit and stop the batch before downstream scoring")
        protocol["files"] = {p.relative_to(target).as_posix(): qa.digest(p.read_bytes())
                             for p in sorted(target.rglob("*")) if p.is_file() and p != target / "protocol.json"}
        qa.write(target / "protocol.json", protocol)
    protocol = qa.read(root / "protocol.json")
    protocol.update(schema="principia-leaderboard-v1", groups=GROUPS, shuffle_seed=20260910,
                    scope_revision="v1.2.1 dev 36 inputs, 18 families, 3 independent repeats; new runs for every arm",
                    pre_run_revision="common numbered source/search evidence; eight current configurations",
                    quality_reviewed=False, planned_sessions=36 * args.replicates * 8,
                    ranking_gate="complete identity-matched question x replicate grid plus blinded source-grounded semantic review; null for unreviewed, never zero",
                    statistics="equal-weight three-category strict success; paired bootstrap of 18 fact families; two paraphrases and replicates remain within family",
                    cost_policy="reported usage and unknown attempts separate; review and construction separate; unknown actual charge stays null")
    protocol["files"] = {p.relative_to(root).as_posix(): qa.digest(p.read_bytes()) for p in sorted(root.rglob("*"))
                         if p.is_file() and p != root / "protocol.json"}
    qa.write(root / "protocol.json", protocol)
    base.verify(root)
    print(qa.wire({"prepared": str(root), "planned_sessions": protocol["planned_sessions"], "protocol_sha256": qa.digest((root / "protocol.json").read_bytes())}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "verify", "run", "replay", "smoke"])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--structure", type=Path)
    parser.add_argument("--relations", type=Path)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    if args.command == "prepare":
        if args.replicates != 3:
            raise ValueError("main leaderboard requires three replicates")
        prepare(args)
        return
    root = args.run.resolve()
    protocol = base.verify(root)
    base.verify_runtime(protocol)
    if args.command == "verify":
        print("PASS: frozen identity")
        return
    if Path(__file__).resolve() != root / "runner.py":
        raise ValueError("execute frozen runner")
    base.SECRET = args.key_file.read_text().strip() if args.key_file else ""
    with (root / "runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install()
        base.reset_transport_circuit()
        engines = {group: base.Engine(root / group, group) for group in GROUPS}
        if args.command == "smoke":
            checks = []
            for group, methods in GROUPS.items():
                for method in methods:
                    session = Session(engines[group], method, "movingCone dynamicMeshDict")
                    action = {"action": "search", "query": "movingCone"} if method == "no_graph" else {"action": "locate"}
                    result, accounting = session.dispatch(action, 6000)
                    if result.get("status") == "tool_error":
                        raise ValueError(qa.wire(result))
                    checks.append({"group": group, "method": method, "result": result, "accounting": accounting})
            qa.write(root / "verification/adapter-smoke.json", checks)
            print("PASS: eight adapter checks; zero model calls")
            return
        questions = qa.read(root / "control/questions.json")
        jobs = [(group, q, method, rep) for q in questions if not args.only or q["id"] in args.only
                for rep in range(1, protocol["replicates"]+1) for group, methods in GROUPS.items() for method in methods]
        random.Random(protocol["shuffle_seed"]).shuffle(jobs)
        begin = time.monotonic()
        journal = root / "invocations" / f"{time.time_ns()}.json"
        state = {"pid": os.getpid(), "state": "running", "command": args.command, "jobs": len(jobs), "workers": args.workers}
        qa.write(journal, state)
        errors, completed = [], 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {}
            for group, question, method, rep in jobs:
                name = f"{question['id']}--{method}--r{rep}"
                if args.command == "run" and (root / group / "sessions" / name / "result.json").exists():
                    completed += 1
                    continue
                pending[pool.submit(base.run_one, engines[group], question, method, base.SECRET or None, rep, args.command == "replay")] = group + "/" + name
            for future in as_completed(pending):
                try:
                    result = future.result()
                    completed += 1
                    print("DONE", pending[future], result["status"], flush=True)
                except Exception as error:
                    errors.append({"session": pending[future], "error_type": type(error).__name__})
                    print("ERROR", pending[future], type(error).__name__, flush=True)
                qa.write(journal, {**state, "completed": completed, "errors": errors, "elapsed_seconds": time.monotonic()-begin})
        outage = any(error["error_type"] == "GlobalTransportOutage" for error in errors)
        base.verify(root)
        qa.write(journal, {**state, "state": "network_circuit_open" if outage else "finished",
                           "completed": completed, "errors": errors, "elapsed_seconds": time.monotonic()-begin})
        print(qa.wire({"completed": completed, "errors": errors}))
        if outage:
            raise SystemExit(75)


if __name__ == "__main__":
    main()
