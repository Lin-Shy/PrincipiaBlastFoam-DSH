"""Four-arm natural-language benchmark: no graph, two Graphify arms, and index-free Principia graph."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import os
from pathlib import Path
import random
import shutil
import time

import candidate_qa as candidate
import graphify_qa as base
import leaderboard_audit as audit
import navigation_qa as qa


BASELINES = {"control": ["no_graph"], "native": ["graph_first"], "text_adapter": ["graph_first"]}
GROUPS = {**BASELINES, "principia_index_free": ["graph_first"]}


def read_secret(key_file: Path | None, settings_file: Path | None) -> str:
    if key_file is not None and settings_file is not None:
        raise ValueError("choose either --key-file or --settings-file")
    if key_file is not None:
        return key_file.read_text().strip()
    if settings_file is None:
        return ""
    settings = {}
    for line in settings_file.read_text().splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            settings[name.strip()] = value.strip()
    secret = settings.get("API_KEY", "")
    if not secret:
        raise ValueError("DeepSeek API key is empty")
    return secret


def prepare(args):
    if args.replicates not in {1, 3}:
        raise ValueError("development screening uses one repeat; finalists use three")
    original_groups = base.GROUPS
    try:
        base.GROUPS = BASELINES
        base.prepare(args)
    finally:
        base.GROUPS = original_groups
    root, graph = args.run.resolve(), args.graph.resolve()
    validation = args.graph_validation.resolve()
    checked = qa.read(validation)
    if checked.get("status") != "passed" or checked.get("graph_sha256") != qa.digest(graph.read_bytes()):
        raise ValueError("independent graph validation gate failed")
    shutil.copy2(graph, root / "principia-graph.json")
    shutil.copy2(validation, root / "principia-graph-validation.json")
    shutil.copytree(root / "control", root / "principia_index_free")
    arm = root / "principia_index_free"
    arm_protocol = qa.read(arm / "protocol.json")
    arm_protocol.update(arm="principia_index_free", methods=["graph_first"],
        prompts={"graph_first": candidate.prompt(candidate.DEFAULTS)}, graph_baseline=None,
        graph_query="direct scan of persisted graph fields, exact identifiers, term coverage, scope constraints and bounded paths",
        external_retrieval_index=False, forbidden_retrieval=("E5", "BM25", "vector store", "inverted index", "passage embeddings"),
        graph_evidence="only exact numbered lines re-read from authoritative original paths are credited",
        options=candidate.DEFAULTS)
    arm_protocol["files"] = {p.relative_to(arm).as_posix(): qa.digest(p.read_bytes())
                              for p in sorted(arm.rglob("*")) if p.is_file() and p != arm / "protocol.json"}
    qa.write(arm / "protocol.json", arm_protocol)
    runtime_names = ("graphify_qa.py", "leaderboard_audit.py", "candidate_graph_utils.py", "candidate_paths.py",
                     "index_free_graph_evidence.py", "candidate_qa.py", "natural_index_free_leaderboard.py")
    source = Path(__file__).parent
    for name in runtime_names:
        shutil.copy2(source / name, root / name)
    shutil.copy2(Path(__file__), root / "runner.py")
    protocol = qa.read(root / "protocol.json")
    protocol.update(schema="chapter2-natural-index-free-four-arm-v1", groups=GROUPS,
        replicates=args.replicates, planned_sessions=len(qa.read(root / "control/questions.json")) * args.replicates * 4,
        model="deepseek-flash", independent_principia_graph=True, external_retrieval_index=False,
        principia_graph_sha256=qa.digest((root / "principia-graph.json").read_bytes()),
        principia_graph_validation_sha256=qa.digest((root / "principia-graph-validation.json").read_bytes()),
        options=candidate.DEFAULTS,
        comparison="same questions, source corpus, model, decision limits and returned-character limits",
        response_read_timeout_seconds=180,
        selection_phase="development_screen" if args.replicates == 1 else "development_finalists",
        holdout_unlocked=False)
    protocol["files"] = {p.relative_to(root).as_posix(): qa.digest(p.read_bytes())
                          for p in sorted(root.rglob("*")) if p.is_file() and p != root / "protocol.json"}
    qa.write(root / "protocol.json", protocol)
    audit.verify(root)
    print(qa.wire({"prepared": str(root), "groups": GROUPS, "planned_sessions": protocol["planned_sessions"]}))


def run_logged(engine, runner, question, method, key, replicate, replay):
    return runner(engine, question, method, key, replicate, replay)


def execute(args):
    root = args.run.resolve()
    protocol = audit.verify(root)
    if protocol.get("model") != "deepseek-flash" or protocol.get("external_retrieval_index") is not False:
        raise ValueError("model or index-free protocol drift")
    base.verify_runtime(protocol)
    if Path(__file__).resolve() != root / "runner.py":
        raise ValueError("execute frozen runner")
    base.SECRET = read_secret(args.key_file, args.settings_file)
    base.reset_transport_circuit();base.install()
    engines = {arm: base.Engine(root / arm, arm) for arm in BASELINES}
    engines["principia_index_free"] = candidate.Engine(root / "principia_index_free", "principia_index_free",
                                                         root / "principia-graph.json", protocol.get("options"))
    runners = {arm: base.run_one for arm in BASELINES}
    runners["principia_index_free"] = candidate.run_one
    if args.command == "smoke":
        session = candidate.Session(engines["principia_index_free"], "graph_first", "movingCone 网格运动配置在哪里？")
        result, accounting = session.dispatch({"action": "locate", "translation": "movingCone mesh motion configuration",
                                               "needs": ["configuration path"]}, 6000)
        if result.get("status") != "ok" or not result.get("evidence") or accounting["candidate_audit"]["external_index_loaded"]:
            raise ValueError("index-free graph smoke failed")
        qa.write(root / "verification/index-free-smoke.json", {"result": result, "accounting": accounting})
        audit.verify(root);print("PASS: index-free graph query and original evidence, zero model calls");return
    questions = qa.read(root / "control/questions.json")
    jobs = [(arm, question, method, replicate) for question in questions
            if not args.only or question["id"] in args.only
            for replicate in range(1, protocol["replicates"] + 1)
            for arm, methods in GROUPS.items() for method in methods]
    random.Random(protocol["shuffle_seed"]).shuffle(jobs)
    state = {"pid": os.getpid(), "state": "running", "jobs": len(jobs), "completed": 0, "errors": [], "command": args.command}
    journal = root / "invocations" / f"{time.time_ns()}.json";begin = time.monotonic();qa.write(journal, state)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        for arm, question, method, replicate in jobs:
            name = f"{question['id']}--{method}--r{replicate}"
            if args.command == "run" and (root / arm / "sessions" / name / "result.json").exists():
                state["completed"] += 1;continue
            pending[pool.submit(run_logged, engines[arm], runners[arm], question, method,
                                base.SECRET or None, replicate, args.command == "replay")] = arm + "/" + name
        for future in as_completed(pending):
            try:
                result = future.result();state["completed"] += 1
                print("DONE", pending[future], result["status"], flush=True)
            except Exception as error:
                state["errors"].append({"session": pending[future], "type": type(error).__name__})
                print("ERROR", pending[future], type(error).__name__, flush=True)
            qa.write(journal, {**state, "elapsed_seconds": time.monotonic() - begin})
    outage = any(row["type"] == "GlobalTransportOutage" for row in state["errors"])
    qa.write(journal, {**state, "state": "network_circuit_open" if outage else "finished",
                       "elapsed_seconds": time.monotonic() - begin})
    audit.verify(root)
    print(qa.wire({"completed": state["completed"], "requested": len(jobs), "errors": state["errors"]}))
    if outage:
        raise SystemExit(75)
    if state["errors"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "smoke", "run", "replay"))
    parser.add_argument("--run", type=Path, required=True);parser.add_argument("--archive", type=Path)
    parser.add_argument("--dataset", type=Path);parser.add_argument("--graph", type=Path)
    parser.add_argument("--graph-validation", type=Path);parser.add_argument("--split", default="dev")
    parser.add_argument("--replicates", type=int, default=1);parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--key-file", type=Path);parser.add_argument("--settings-file", type=Path)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args);return
    if args.command == "verify":
        audit.verify(args.run.resolve());print("PASS: frozen four-arm identity");return
    with (args.run.resolve() / "runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB);execute(args)


if __name__ == "__main__":
    main()
