"""SiliconFlow Qwen3 five-arm Chapter 2 runs on the frozen v7r1 dataset."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import os
from pathlib import Path
import random
import shutil
import time

import candidate_qa as candidate
import graphify_qa as graphify
import leaderboard_audit as audit
import navigation_qa as qa
import vector_retrieval_qa as vector
from chapter2_siliconflow_config import BASE_URL, MODELS, configure_qa, read_settings
from chapter2_siliconflow_throttle import PacedUrlopen

GROUPS = {"control": "no_graph", "native": "graph_first", "text_adapter": "graph_first",
          "principia_index_free": "graph_first", "vector_e5_dense": "retrieval_first"}
RUNTIME_FILES = ("navigation_qa.py", "graphify_query_backend.py", "graphify_qa.py", "candidate_qa.py",
                 "candidate_graph_utils.py", "candidate_paths.py", "index_free_graph_evidence.py",
                 "candidate_hybrid.py", "vector_retrieval_qa.py", "leaderboard_audit.py",
                 "build_natural_navigation_v2.py", "build_natural_navigation_v6.py",
                 "chapter2_siliconflow_config.py", "chapter2_siliconflow_throttle.py")


def prepare(args):
    run = args.run.resolve()
    if run.exists():
        raise FileExistsError("use a new output directory")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("set PYTHONHASHSEED=0 before launching Python")
    model = configure_qa(qa, args.model_size)
    if args.split == "holdout":
        if args.replicates != 3 or not args.freeze_gate or not args.freeze_gate.is_file():
            raise ValueError("holdout requires three repeats and a frozen development gate")
        gate = qa.read(args.freeze_gate)
        if not gate.get("implementation_frozen") or gate.get("dataset_manifest_sha256") != qa.digest((args.dataset / "manifest.json").read_bytes()):
            raise ValueError("invalid holdout freeze gate")
        dev_root = Path(gate["dev_runs"]["path"])
        if qa.digest((dev_root / "protocol.json").read_bytes()) != gate["dev_runs"]["protocol_sha256"]:
            raise ValueError("development protocol drift after freeze")
        for name, expected in gate["runtime_files_sha256"].items():
            if qa.digest((Path(__file__).parent / name).read_bytes()) != expected:
                raise ValueError("runtime implementation drift: " + name)
        if qa.digest((args.parent / "principia-graph.json").read_bytes()) != gate["graph_sha256"]:
            raise ValueError("self graph drift after freeze")
        if qa.digest((args.e5_index / "manifest.json").read_bytes()) != gate["vector_index_manifest_sha256"]:
            raise ValueError("E5 index drift after freeze")
    elif args.replicates != 1:
        raise ValueError("development selection uses one repeat")
    dataset_manifest = qa.read(args.dataset / "manifest.json")
    for name, expected in dataset_manifest["artifacts"].items():
        if qa.digest((args.dataset / name).read_bytes()) != expected:
            raise ValueError("dataset drift: " + name)
    parent = args.parent.resolve()
    parent_protocol = audit.verify(parent)
    if parent_protocol.get("external_retrieval_index") is not False:
        raise ValueError("parent final method must be index-free")
    graph = parent / "principia-graph.json"
    validation = qa.read(parent / "principia-graph-validation.json")
    if validation.get("status") != "passed" or validation.get("graph_sha256") != qa.digest(graph.read_bytes()):
        raise ValueError("independent graph validation failed")
    index = args.e5_index.resolve()
    im = qa.read(index / "manifest.json")
    for name, expected in im["files"].items():
        if qa.digest((index / name).read_bytes()) != expected:
            raise ValueError("E5 comparator index drift")
    run.mkdir(parents=True)
    source = Path(__file__).parent
    for name in RUNTIME_FILES:
        shutil.copy2(source / name, run / name)
    shutil.copy2(__file__, run / "runner.py")
    shutil.copy2(graph, run / "principia-graph.json")
    shutil.copy2(parent / "principia-graph-validation.json", run / "principia-graph-validation.json")
    shutil.copytree(index, run / "vector-index")
    for arm, method in GROUPS.items():
        parent_arm = parent / ("control" if arm == "vector_e5_dense" else arm)
        original = qa.read(parent_arm / "protocol.json")
        target = run / arm
        for name, expected in original["files"].items():
            if name.startswith("evaluation_only/") or name == "questions.json":
                continue
            src = parent_arm / name
            if qa.digest(src.read_bytes()) != expected:
                raise ValueError("parent arm drift: " + arm + "/" + name)
            dst = target / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        shutil.copy2(args.dataset / f"{args.split}.questions.json", target / "questions.json")
        private = target / "evaluation_only"
        private.mkdir(exist_ok=True)
        shutil.copy2(args.dataset / f"{args.split}.annotations.json", private / "annotations.json")
        shutil.copy2(args.dataset / "scoring-rules.json", private / "scoring-rules.json")
        prompt = vector.prompt(candidate.DEFAULTS) if arm == "vector_e5_dense" else (
            candidate.prompt(candidate.DEFAULTS) if arm == "principia_index_free" else graphify.prompt(method))
        protocol = {"schema": "chapter2-siliconflow-arm-v1", "arm": arm, "methods": [method],
                    "model": model, "provider": "siliconflow", "endpoint": BASE_URL,
                    "split": args.split, "replicates": args.replicates,
                    "limits": qa.LIMITS, "prompts": {method: prompt}, "final": qa.FINAL,
                    "dataset_manifest_sha256": qa.digest((args.dataset / "manifest.json").read_bytes()),
                    "external_retrieval_index": arm == "vector_e5_dense",
                    "files": {p.relative_to(target).as_posix(): qa.digest(p.read_bytes()) for p in sorted(target.rglob("*")) if p.is_file()}}
        qa.write(target / "protocol.json", protocol)
    frozen = {p.relative_to(run).as_posix(): qa.digest(p.read_bytes()) for p in sorted(run.rglob("*"))
              if p.is_file() and p.name != "protocol.json" or p.is_file() and p.parent != run and p.name == "protocol.json"}
    protocol = {"schema": "chapter2-siliconflow-five-arm-v1", "groups": {k: [v] for k, v in GROUPS.items()},
                "split": args.split, "replicates": args.replicates, "model": model,
                "provider": "siliconflow", "endpoint": BASE_URL,
                "transport_pacing": {"minimum_gap_seconds": 6.0, "rate_limit_pause_seconds": 75.0},
                "dataset_manifest_sha256": qa.digest((args.dataset / "manifest.json").read_bytes()),
                "parent_graph_sha256": qa.digest(graph.read_bytes()), "vector_index_manifest_sha256": qa.digest((index / "manifest.json").read_bytes()),
                "runtime_identity": graphify.runtime_identity(), "shuffle_seed": 20260928,
                "planned_sessions": len(qa.read(run / "control/questions.json")) * len(GROUPS) * args.replicates,
                "frozen_gate_sha256": qa.digest(args.freeze_gate.read_bytes()) if args.freeze_gate else None,
                "failure_policy": "retry only the identical transport request; keep failed attempts",
                "files": frozen}
    qa.write(run / "protocol.json", protocol)
    audit.verify(run)
    print(qa.wire({"prepared": str(run), "split": args.split, "sessions": protocol["planned_sessions"]}))


def execute(args):
    run = args.run.resolve()
    protocol = audit.verify(run)
    graphify.verify_runtime(protocol)
    if Path(__file__).resolve() != run / "runner.py":
        raise ValueError("execute the frozen runner")
    if protocol.get("schema") != "chapter2-siliconflow-five-arm-v1" or protocol.get("model") not in MODELS.values():
        raise ValueError("not a Chapter 2 SiliconFlow run")
    model_size = next(size for size, model in MODELS.items() if model == protocol["model"])
    configure_qa(qa, model_size)
    pacing = protocol["transport_pacing"]
    graphify.urlopen = PacedUrlopen(pacing["minimum_gap_seconds"], pacing["rate_limit_pause_seconds"])
    graphify.SECRET = read_settings(args.settings_file) if args.command == "run" else ""
    graphify.reset_transport_circuit()
    graphify.install()
    selected = set(args.only_arm or GROUPS)
    engines = {}
    for arm in GROUPS:
        if arm not in selected:
            continue
        begin_load = time.monotonic()
        if arm in ("control", "native", "text_adapter"):
            engines[arm] = graphify.Engine(run / arm, arm)
        elif arm == "principia_index_free":
            engines[arm] = candidate.Engine(run / arm, arm, run / "principia-graph.json", candidate.DEFAULTS)
        else:
            engines[arm] = vector.Engine(run / arm, arm, run / "vector-index", candidate.DEFAULTS)
        qa.write(run / arm / f"startup-load-{time.time_ns()}.json",
                 {"seconds": time.monotonic() - begin_load, "scope": "arm engine construction until query ready"})
    runners = {arm: graphify.run_one for arm in ("control", "native", "text_adapter")}
    runners["principia_index_free"] = candidate.run_one
    runners["vector_e5_dense"] = vector.run_one
    if args.command == "smoke":
        for arm in ("principia_index_free", "vector_e5_dense"):
            if arm not in engines:
                continue
            session = engines[arm].session_type(engines[arm], GROUPS[arm], "movingCone mesh motion") if hasattr(engines[arm], "session_type") else candidate.Session(engines[arm], GROUPS[arm], "movingCone mesh motion")
            result, accounting = session.dispatch({"action": "locate", "query": "mesh motion", "needs": ["configuration"]}, 6000)
            if result.get("status") != "ok":
                raise ValueError("smoke failed: " + arm)
        print("PASS: graph and E5 comparator query smoke")
        return
    questions = qa.read(run / "control/questions.json")
    if args.question_id:
        if protocol["split"] != "dev":
            raise ValueError("question selection is permitted only on the development split")
        ids = set(args.question_id)
        questions = [q for q in questions if q["id"] in ids]
        if {q["id"] for q in questions} != ids:
            raise ValueError("unknown development question ID")
    jobs = [(arm, question, GROUPS[arm], rep) for question in questions for rep in range(1, protocol["replicates"] + 1)
            for arm in GROUPS if not args.only_arm or arm in args.only_arm]
    random.Random(protocol["shuffle_seed"]).shuffle(jobs)
    state = {"pid": os.getpid(), "state": "running", "jobs": len(jobs), "completed": 0,
             "errors": [], "workers": args.workers, "command": args.command,
             "question_ids": [q["id"] for q in questions], "model": qa.MODEL,
             "started_unix_ns": time.time_ns()}
    journal = run / "invocations" / f"{state['started_unix_ns']}.json"
    started = time.monotonic()
    qa.write(journal, state)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        for arm, question, method, rep in jobs:
            folder = run / arm / "sessions" / f"{question['id']}--{method}--r{rep}"
            if args.command == "run" and (folder / "result.json").exists():
                state["completed"] += 1
                continue
            runner = runners[arm] if arm in ("control", "native", "text_adapter") else run_with_timing
            pending[pool.submit(runner, engines[arm], question, method,
                                graphify.SECRET or None, rep, args.command == "replay")] = arm + "/" + folder.name
        for future in as_completed(pending):
            try:
                result = future.result()
                state["completed"] += 1
                print("DONE", pending[future], result["status"], flush=True)
            except Exception as error:
                state["errors"].append({"session": pending[future], "type": type(error).__name__})
                print("ERROR", pending[future], type(error).__name__, flush=True)
            qa.write(journal, {**state, "elapsed_seconds": time.monotonic() - started})
    state["state"] = "finished"
    state["elapsed_seconds"] = time.monotonic() - started
    qa.write(journal, state)
    audit.verify(run)
    print(qa.wire({"completed": state["completed"], "requested": len(jobs), "errors": state["errors"]}))
    if state["errors"]:
        raise SystemExit(1)


def run_with_timing(engine, question, method, key, replicate, replay):
    folder = engine.run / "sessions" / f"{question['id']}--{method}--r{replicate}"
    started_ns = time.time_ns()
    started = time.monotonic()
    status = "error"
    try:
        runner = vector.run_one if engine.run.name == "vector_e5_dense" else candidate.run_one
        result = runner(engine, question, method, key, replicate, replay)
        status = result["status"]
        return result
    finally:
        qa.write(folder / "invocations" / f"{started_ns}.json",
                 {"status": status, "replay": replay, "started_unix_ns": started_ns,
                  "elapsed_seconds": time.monotonic() - started})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "verify", "smoke", "run", "replay"))
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--dataset", type=Path)
    p.add_argument("--parent", type=Path)
    p.add_argument("--e5-index", type=Path)
    p.add_argument("--split", choices=("dev", "holdout"), default="dev")
    p.add_argument("--freeze-gate", type=Path)
    p.add_argument("--replicates", type=int, default=1)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only-arm", nargs="*")
    p.add_argument("--settings-file", type=Path)
    p.add_argument("--model-size", choices=tuple(MODELS), default="8b")
    p.add_argument("--question-id", action="append")
    a = p.parse_args()
    if a.command == "prepare":
        prepare(a)
        return
    if a.command == "verify":
        audit.verify(a.run)
        print("PASS: frozen SiliconFlow five-arm inputs")
        return
    with (a.run / "runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(a)


if __name__ == "__main__":
    main()
