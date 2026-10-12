"""Post-hoc evaluation of context-expanded source reads for two-stage Principia."""
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
from index_free_graph_evidence import NAVIGATION_CANDIDATE_LIMIT


GROUPS = {
    "principia_navigation_context16": ["graph_first"],
}
OPTIONS = {
    "principia_navigation_context16": {
        **candidate.DEFAULTS,
        "navigation_only": True,
        "navigation_extra_candidates": 0,
        "exploration_decisions": 6,
        "source_context_lines": 16,
    },
}
RUNTIME_NAMES = (
    "graphify_qa.py",
    "graphify_query_backend.py",
    "leaderboard_audit.py",
    "candidate_graph_utils.py",
    "candidate_paths.py",
    "index_free_graph_evidence.py",
    "candidate_qa.py",
    "navigation_catalogue_evaluation.py",
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
    if not args.baseline_quality or not args.predecessor_quality or not args.vector_quality:
        raise ValueError("freeze baseline, predecessor, and vector quality inputs")
    baseline_quality = qa.read(args.baseline_quality.resolve())
    predecessor_quality = qa.read(args.predecessor_quality.resolve())
    vector_quality = qa.read(args.vector_quality.resolve())
    if not baseline_quality.get("all_arms_rankable"):
        raise ValueError("baseline quality is not fully rankable")
    if not predecessor_quality.get("all_arms_rankable"):
        raise ValueError("predecessor navigation quality is not fully rankable")
    if not vector_quality.get("all_arms_rankable"):
        raise ValueError("vector comparator quality is not fully rankable")
    expected_baseline_arms = {
        "control", "native", "text_adapter", "principia_index_free",
    }
    if {row["arm"] for row in baseline_quality.get("arms", [])} != expected_baseline_arms:
        raise ValueError("unexpected frozen baseline arms")
    if {row["arm"] for row in predecessor_quality.get("arms", [])} != {
        "candidate010_evidence", "candidate010_navigation",
    }:
        raise ValueError("unexpected predecessor navigation arms")
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
            strategy=(
                "six exploration decisions plus claim plan, draft and semantic "
                "verification; compact graph-only candidate cards expose bounded "
                "persisted node values, parent/child hints and relation endpoint labels; "
                "after model selection, authoritative original ranges receive an adaptive "
                "symmetric context window of at most 16 lines"
            ),
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
        schema="chapter2-principia-navigation-selected-source-context-posthoc-v3",
        groups=GROUPS,
        options_by_arm=OPTIONS,
        replicates=1,
        planned_sessions=len(questions),
        model="deepseek-flash",
        shuffle_seed=20260926,
        split="dev",
        holdout_unlocked=False,
        external_retrieval_index=False,
        graph_nodes=manifest["nodes"],
        graph_edges=manifest["edges"],
        runtime_graph_sha256=manifest["runtime_graph_sha256"],
        full_graph_sha256=manifest["source_graph_sha256"],
        comparison=(
            "same v5 development questions, persisted graph, corpus, deepseek-flash, "
            "answer verifier and 24000-character session budget as the frozen runs; "
            "locate keeps the original evidence-budgeted candidate admission and original "
                "text remains available only through explicit model-selected read_sources; "
            "selected source spans receive up to 16 adjacent authoritative original lines, "
            "shrunk deterministically when necessary so all selected spans fit the current "
            "response budget"
        ),
        phase="posthoc_two_stage_selected_source_context_validation_not_candidate011",
        user_authorized_objective=(
            "retain a two-stage interface and seek a method superior to Graphify, "
            "text retrieval and vector retrieval; matching evidence-first is not required"
        ),
        catalogue_policy={
            "budget_basis": "evidence_budget_only",
            "candidate_limit": NAVIGATION_CANDIDATE_LIMIT,
            "compact_overflow_limit": 0,
            "graph_card_fields": (
                "bounded persisted node identity/value plus compact parent/children "
                "hints and labeled relation endpoints; no raw source text"
            ),
            "selected_source_context": (
                "at most 16 original lines on each side; overlaps merged per file; "
                "one shared window shrinks to fit the live response cap"
            ),
            "persistent_external_index": False,
        },
        maximum_model_calls=9,
        maximum_generated_tokens=8000,
        exploration_decisions=6,
        baseline_quality={
            "path": str(args.baseline_quality.resolve()),
            "sha256": qa.digest(args.baseline_quality.resolve().read_bytes()),
        },
        predecessor_navigation_quality={
            "path": str(args.predecessor_quality.resolve()),
            "sha256": qa.digest(args.predecessor_quality.resolve().read_bytes()),
        },
        vector_quality={
            "path": str(args.vector_quality.resolve()),
            "sha256": qa.digest(args.vector_quality.resolve().read_bytes()),
        },
        selection_gate={
            "strict_success_macro": (
                "point estimate greater than frozen no_graph text arm, both Graphify "
                "arms, and the frozen dense-vector comparator"
            ),
            "citation_accuracy": "at least 0.90",
            "required_evidence_recall": "at least 0.80",
            "navigation_contract": (
                "all navigation locate calls return no original text; at least 95% "
                "of answered sessions use read_sources after locate"
            ),
            "decision": (
                "select only if every quality and navigation-contract gate passes"
            ),
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
    parser.add_argument("--baseline-quality", type=Path)
    parser.add_argument("--predecessor-quality", type=Path)
    parser.add_argument("--vector-quality", type=Path)
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
