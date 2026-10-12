"""Freeze and run a dense-only E5 whole-system comparator on v5 development QA."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import importlib.metadata
import os
from pathlib import Path
import random
import shutil
import time

import candidate_qa as candidate
import graphify_qa as base
import leaderboard_audit as audit
import navigation_qa as qa
import vector_retrieval_qa as vector


GROUPS = {"vector_e5_dense": ["retrieval_first"]}
OPTIONS = {**candidate.DEFAULTS, "navigation_only": False}
RUNTIME_NAMES = (
    "candidate_graph_utils.py", "candidate_hybrid.py", "candidate_paths.py",
    "candidate_qa.py", "index_free_graph_evidence.py", "graphify_qa.py",
    "graphify_query_backend.py", "leaderboard_audit.py", "navigation_qa.py",
    "vector_retrieval_qa.py", "vector_comparator_evaluation.py",
)


def read_secret(settings_file):
    values = {}
    for line in Path(settings_file).read_text().splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    if not values.get("API_KEY"):
        raise ValueError("DeepSeek API key is empty")
    return values["API_KEY"]


def prepare(args):
    if args.replicates != 1:
        raise ValueError("post-hoc comparator uses one frozen repeat")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("freeze with PYTHONHASHSEED=0")
    index = args.index.resolve()
    index_manifest = qa.read(index / "manifest.json")
    for name, expected in index_manifest["files"].items():
        if qa.digest((index / name).read_bytes()) != expected:
            raise ValueError("vector index drift")
    baseline = qa.read(args.baseline_quality.resolve())
    navigation = qa.read(args.navigation_quality.resolve())
    if not baseline.get("all_arms_rankable") or not navigation.get("all_arms_rankable"):
        raise ValueError("frozen comparison quality is incomplete")

    original_groups = base.GROUPS
    try:
        base.GROUPS = {"control": ["no_graph"]}
        base.prepare(args)
    finally:
        base.GROUPS = original_groups

    root = args.run.resolve()
    template = root / "control"
    arm = root / "vector_e5_dense"
    shutil.copytree(template, arm)
    arm_protocol = qa.read(arm / "protocol.json")
    arm_protocol.update(
        schema="chapter2-vector-e5-dense-arm-v1",
        arm="vector_e5_dense",
        methods=["retrieval_first"],
        prompts={"retrieval_first": vector.prompt(OPTIONS)},
        options=OPTIONS,
        graph_loaded=False,
        retrieval=(
            "dense cosine ranking only over frozen raw-corpus passages; no graph, "
            "BM25, exact-match channel, question annotations, or gold"
        ),
        quality_status="unscored; full source-grounded review required",
    )
    arm_protocol["files"] = {
        path.relative_to(arm).as_posix(): qa.digest(path.read_bytes())
        for path in sorted(arm.rglob("*"))
        if path.is_file() and path != arm / "protocol.json"
    }
    qa.write(arm / "protocol.json", arm_protocol)
    shutil.rmtree(template)
    shutil.copytree(index, root / "vector-index")
    source = Path(__file__).parent
    for name in RUNTIME_NAMES:
        shutil.copy2(source / name, root / name)
    shutil.copy2(Path(__file__), root / "runner.py")

    protocol = qa.read(root / "protocol.json")
    questions = qa.read(arm / "questions.json")
    protocol.update(
        schema="chapter2-posthoc-vector-e5-comparator-v1",
        groups=GROUPS,
        replicates=1,
        planned_sessions=len(questions),
        model="deepseek-flash",
        shuffle_seed=20260923,
        split="dev",
        holdout_unlocked=False,
        external_retrieval_index=True,
        comparator_only=True,
        final_method_index_policy=(
            "this vector index is forbidden from the selected Principia method and "
            "exists only under the comparator evaluation"
        ),
        vector_index={
            "source": str(index),
            "source_manifest_sha256": qa.digest((index / "manifest.json").read_bytes()),
            "model": index_manifest["model"],
            "passages": index_manifest["passages"],
            "embedding_dimensions": index_manifest["embedding_dimensions"],
            "files": index_manifest["files"],
        },
        runtime_packages={
            name: importlib.metadata.version(name)
            for name in ("torch", "sentence-transformers", "transformers", "numpy")
        },
        comparison=(
            "same v5 development questions, frozen raw corpus, deepseek-flash, six "
            "exploration decisions, claim verifier, 24000 returned characters and "
            "source-grounded blind review as the Principia navigation run"
        ),
        baseline_quality={
            "path": str(args.baseline_quality.resolve()),
            "sha256": qa.digest(args.baseline_quality.resolve().read_bytes()),
        },
        navigation_quality={
            "path": str(args.navigation_quality.resolve()),
            "sha256": qa.digest(args.navigation_quality.resolve().read_bytes()),
        },
        phase="posthoc_comparator_only_not_candidate011",
    )
    protocol["files"] = {
        path.relative_to(root).as_posix(): qa.digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and path != root / "protocol.json"
    }
    qa.write(root / "protocol.json", protocol)
    audit.verify(root)
    print(qa.wire({"prepared": str(root), "planned_sessions": len(questions),
                   "holdout_unlocked": False}))


def execute(args):
    root = args.run.resolve()
    protocol = audit.verify(root)
    if Path(__file__).resolve() != root / "runner.py":
        raise ValueError("execute the frozen runner")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("run/replay with PYTHONHASHSEED=0")
    base.verify_runtime(protocol)
    base.SECRET = read_secret(args.settings_file) if args.command == "run" else ""
    base.reset_transport_circuit()
    base.install()
    engine = vector.Engine(root / "vector_e5_dense", "vector_e5_dense",
                           root / "vector-index", OPTIONS)
    if args.command == "smoke":
        session = vector.Session(engine, "retrieval_first", "movingCone dynamicMeshDict mesh motion")
        result, accounting = session.dispatch({"action": "locate", "translation": "",
                                                "query": "", "needs": ["configuration"]}, 6000)
        if (result.get("status") != "ok" or not result.get("items")
                or accounting.get("retrieval_audit", {}).get("retrieval_mode") != "vector"):
            raise ValueError("dense comparator smoke failed")
        qa.write(root / "verification/vector-smoke.json", {"result": result, "accounting": accounting})
        audit.verify(root)
        print("PASS: dense-only vector retrieval and numbered original evidence; zero model calls")
        return

    questions = qa.read(root / "vector_e5_dense" / "questions.json")
    jobs = [question for question in questions if not args.only or question["id"] in args.only]
    random.Random(protocol["shuffle_seed"]).shuffle(jobs)
    journal = root / "invocations" / f"{time.time_ns()}.json"
    state = {"pid": os.getpid(), "state": "running", "command": args.command,
             "jobs": len(jobs), "completed": 0, "errors": []}
    begin = time.monotonic()
    qa.write(journal, state)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        for question in jobs:
            name = f"{question['id']}--retrieval_first--r1"
            if (args.command == "run" and
                    (root / "vector_e5_dense" / "sessions" / name / "result.json").exists()):
                state["completed"] += 1
                continue
            future = pool.submit(vector.run_one, engine, question, "retrieval_first",
                                 base.SECRET or None, 1, args.command == "replay")
            pending[future] = "vector_e5_dense/" + name
        for future in as_completed(pending):
            try:
                result = future.result()
                state["completed"] += 1
                print("DONE", pending[future], result["status"], flush=True)
            except Exception as error:
                state["errors"].append({"session": pending[future], "type": type(error).__name__})
                print("ERROR", pending[future], type(error).__name__, flush=True)
            qa.write(journal, {**state, "elapsed_seconds": time.monotonic() - begin})
    outage = any(row["type"] == "GlobalTransportOutage" for row in state["errors"])
    state.update(state="network_circuit_open" if outage else "finished",
                 elapsed_seconds=time.monotonic() - begin)
    qa.write(journal, state)
    audit.verify(root)
    print(qa.wire({"completed": state["completed"], "requested": len(jobs),
                   "errors": state["errors"]}))
    if outage:
        raise SystemExit(75)
    if state["errors"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "smoke", "run", "replay"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--baseline-quality", type=Path)
    parser.add_argument("--navigation-quality", type=Path)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--replicates", type=int, default=1)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--settings-file", type=Path)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "verify":
        audit.verify(args.run.resolve())
        print("PASS: frozen dense-vector comparator protocol")
    else:
        with (args.run.resolve() / "runtime.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            execute(args)


if __name__ == "__main__":
    main()
