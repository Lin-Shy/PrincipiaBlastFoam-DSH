"""Post-hoc two-arm development evaluation of evidence-first versus navigation-first Principia."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import time

import candidate_qa as candidate
import graphify_qa as base
import leaderboard_audit as audit
import navigation_qa as qa


GROUPS = {
    "candidate010_evidence": ["graph_first"],
    "candidate010_navigation": ["graph_first"],
}
OPTIONS = {
    "candidate010_evidence": {**candidate.DEFAULTS, "navigation_only": False},
    "candidate010_navigation": {**candidate.DEFAULTS, "navigation_only": True},
}
RUNTIME_NAMES = (
    "graphify_qa.py",
    "graphify_query_backend.py",
    "leaderboard_audit.py",
    "candidate_graph_utils.py",
    "candidate_paths.py",
    "index_free_graph_evidence.py",
    "candidate_qa.py",
    "navigation_mode_evaluation.py",
)


def read_secret(settings_file):
    settings = {}
    for line in Path(settings_file).read_text().splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            settings[name.strip()] = value.strip()
    secret = settings.get("API_KEY", "")
    if not secret:
        raise ValueError("DeepSeek API key is empty")
    return secret


def prepare(args):
    if args.replicates != 1:
        raise ValueError("post-hoc development comparison uses one frozen repeat")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("freeze with PYTHONHASHSEED=0")
    original_groups = base.GROUPS
    try:
        base.GROUPS = {"control": ["no_graph"]}
        base.prepare(args)
    finally:
        base.GROUPS = original_groups

    root = args.run.resolve()
    runtime_graph = args.graph.resolve()
    runtime_manifest = args.runtime_manifest.resolve()
    full_validation = args.graph_validation.resolve()
    manifest = qa.read(runtime_manifest)
    validation = qa.read(full_validation)
    if manifest.get("runtime_graph_sha256") != qa.digest(runtime_graph.read_bytes()):
        raise ValueError("runtime graph drift")
    if manifest.get("source_graph_sha256") != validation.get("graph_sha256"):
        raise ValueError("runtime graph source validation drift")
    if (manifest.get("nodes"), manifest.get("edges")) != (
        validation.get("nodes"), validation.get("edges")
    ):
        raise ValueError("runtime graph shape drift")

    template = root / "control"
    for arm, methods in GROUPS.items():
        target = root / arm
        shutil.copytree(template, target)
        protocol = qa.read(target / "protocol.json")
        protocol.update(
            schema="principia-navigation-mode-arm-v1",
            arm=arm,
            methods=methods,
            prompts={"graph_first": candidate.prompt(OPTIONS[arm])},
            options=OPTIONS[arm],
            graph_query=(
                "direct scan of persisted graph fields and bounded graph paths; "
                "no external retrieval index"
            ),
            graph_evidence=(
                "only exact numbered lines explicitly returned from authoritative "
                "original paths are credited"
            ),
            quality_status="unscored; full source-grounded review required",
        )
        protocol["files"] = {
            path.relative_to(target).as_posix(): qa.digest(path.read_bytes())
            for path in sorted(target.rglob("*"))
            if path.is_file() and path != target / "protocol.json"
        }
        qa.write(target / "protocol.json", protocol)
    shutil.rmtree(template)

    shutil.copy2(runtime_graph, root / "principia-runtime-graph.json")
    shutil.copy2(runtime_manifest, root / "principia-runtime-graph.manifest.json")
    shutil.copy2(full_validation, root / "principia-full-graph-validation.json")
    source = Path(__file__).parent
    for name in RUNTIME_NAMES:
        shutil.copy2(source / name, root / name)
    shutil.copy2(Path(__file__), root / "runner.py")

    protocol = qa.read(root / "protocol.json")
    questions = qa.read(root / next(iter(GROUPS)) / "questions.json")
    protocol.update(
        schema="chapter2-principia-navigation-mode-posthoc-v1",
        groups=GROUPS,
        options_by_arm=OPTIONS,
        replicates=1,
        planned_sessions=len(questions) * 2,
        model="deepseek-flash",
        shuffle_seed=20260922,
        split="dev",
        holdout_unlocked=False,
        external_retrieval_index=False,
        graph_nodes=manifest["nodes"],
        graph_edges=manifest["edges"],
        runtime_graph_sha256=manifest["runtime_graph_sha256"],
        full_graph_sha256=manifest["source_graph_sha256"],
        comparison=(
            "same 144 development questions, graph, corpus, model, budgets, ranking "
            "and answer verifier; only locate response mode and explicit candidate "
            "source-selection step differ"
        ),
        phase="posthoc_engineering_validation_not_candidate011",
        replacement_gate={
            "strict_success_macro": "navigation >= evidence",
            "citation_accuracy": "navigation >= evidence",
            "required_evidence_recall": "navigation >= evidence",
            "navigation_contract": (
                "all navigation locate calls return no original text; at least 95% "
                "of answered sessions use read_sources after locate"
            ),
            "efficiency": (
                "navigation first-locate returned characters < evidence first-locate "
                "returned characters"
            ),
            "decision": "replace default only if every gate passes",
        },
    )
    protocol["files"] = {
        path.relative_to(root).as_posix(): qa.digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and path != root / "protocol.json"
    }
    qa.write(root / "protocol.json", protocol)
    audit.verify(root)
    print(qa.wire({
        "prepared": str(root),
        "planned_sessions": protocol["planned_sessions"],
        "groups": GROUPS,
        "holdout_unlocked": False,
    }))


def execute(args):
    root = args.run.resolve()
    protocol = audit.verify(root)
    if Path(__file__).resolve() != root / "runner.py":
        raise ValueError("execute the frozen runner")
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("run/replay with PYTHONHASHSEED=0")
    base.SECRET = read_secret(args.settings_file) if args.command == "run" else ""
    base.reset_transport_circuit()
    base.install()
    engines = {
        arm: candidate.Engine(
            root / arm,
            arm,
            root / "principia-runtime-graph.json",
            protocol["options_by_arm"][arm],
        )
        for arm in GROUPS
    }
    questions = qa.read(root / next(iter(GROUPS)) / "questions.json")
    jobs = [
        (arm, question, method)
        for question in questions
        if not args.only or question["id"] in args.only
        for arm, methods in GROUPS.items()
        for method in methods
    ]
    random.Random(protocol["shuffle_seed"]).shuffle(jobs)
    journal = root / "invocations" / f"{time.time_ns()}.json"
    state = {
        "pid": os.getpid(), "state": "running", "command": args.command,
        "jobs": len(jobs), "completed": 0, "errors": [],
    }
    begin = time.monotonic()
    qa.write(journal, state)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {}
        for arm, question, method in jobs:
            name = f"{question['id']}--{method}--r1"
            if args.command == "run" and (root / arm / "sessions" / name / "result.json").exists():
                state["completed"] += 1
                continue
            future = pool.submit(
                candidate.run_one, engines[arm], question, method,
                base.SECRET or None, 1, args.command == "replay",
            )
            pending[future] = arm + "/" + name
        for future in as_completed(pending):
            try:
                result = future.result()
                state["completed"] += 1
                print("DONE", pending[future], result["status"], flush=True)
            except Exception as error:
                state["errors"].append({
                    "session": pending[future], "type": type(error).__name__,
                })
                print("ERROR", pending[future], type(error).__name__, flush=True)
            qa.write(journal, {**state, "elapsed_seconds": time.monotonic() - begin})
    outage = any(row["type"] == "GlobalTransportOutage" for row in state["errors"])
    state.update(
        state="network_circuit_open" if outage else "finished",
        elapsed_seconds=time.monotonic() - begin,
    )
    qa.write(journal, state)
    audit.verify(root)
    print(qa.wire({
        "completed": state["completed"], "requested": len(jobs),
        "errors": state["errors"],
    }))
    if outage:
        raise SystemExit(75)
    if state["errors"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "run", "replay"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--graph-validation", type=Path)
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
        print("PASS: frozen post-hoc navigation-mode protocol")
    else:
        with (args.run.resolve() / "runtime.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            execute(args)


if __name__ == "__main__":
    main()
